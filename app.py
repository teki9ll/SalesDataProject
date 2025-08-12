from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, Depends, UploadFile, File, Form
from sqlmodel import SQLModel, Field, Session, create_engine, select
import pandas as pd
from sqlmodel import func, desc
from sqlalchemy import text
import time
import logging
import os
from datetime import datetime, date
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# SQLite database file
sqlite_file_name = "sales_data.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# Connect args needed for SQLite multi-threading with FastAPI
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# Define models for Customer and Brand sales detail with purchase_month
class Customer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_code: str = Field(index=True)
    salesman: Optional[str] = None
    total_bought: float = 0.0
    brand_count: int = 0

class BrandSale(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    brand_code: str = Field(index=True)
    customer_id: int = Field(foreign_key="customer.id")
    amount: float = 0.0
    purchase_month: date = Field(index=True)  # store as first day of month

# Create tables function
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Dependency to get DB session
def get_session():
    with Session(engine) as session:
        yield session

app = FastAPI()

# Utility to parse purchase month string to date (YYYY-MM)
def parse_month_to_date(month_str: str) -> date:
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.date().replace(day=1)
    except Exception:
        raise ValueError("Invalid month format. Expected YYYY-MM")

@app.on_event("startup")
def on_startup():
    logger.info("Starting application...")
    create_db_and_tables()

    with Session(engine) as session:
        customer_exists = session.exec(select(Customer).limit(1)).first()
        if not customer_exists:
            logger.info("Database empty: Waiting for client to upload data via API before queries can work.")
        else:
            logger.info("Database has existing data; ready for queries.")

# API: Upload Excel Month Data - replaces existing month data for customers/brands
@app.post("/upload-month-data/")
async def upload_month_data(
    purchase_month_str: str = Form(..., description="Month in YYYY-MM format"),
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    try:
        purchase_month = parse_month_to_date(purchase_month_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    contents = await file.read()
    df = pd.read_excel(BytesIO(contents), header=4)
    df.rename(columns={df.columns[0]: 'CustomerCode', df.columns[1]: 'Salesman', df.columns[2]: 'Total'}, inplace=True)
    brand_cols = df.columns[3:-1]
    count_col = df.columns[-1]

    cust_codes_in_file = set(str(code).strip() for code in df['CustomerCode'] if str(code).strip().isdigit())

    # Get existing customers matching codes
    existing_customers = session.exec(
        select(Customer).where(Customer.customer_code.in_(cust_codes_in_file))
    ).all()
    existing_cust_code_map = {c.customer_code: c for c in existing_customers}

    try:
        # Delete existing brand sales for this month & customers in file
        customer_ids = [c.id for c in existing_customers]
        if customer_ids:
            stmt = text("DELETE FROM brandsale WHERE purchase_month = :pm AND customer_id IN :ids")
            session.exec(stmt.bindparams(pm=purchase_month, ids=tuple(customer_ids)))
            session.commit()

        inserted_customers = 0
        inserted_brand_sales = 0

        for idx, row in df.iterrows():
            cust_code = str(row['CustomerCode']).strip()
            if not cust_code.isdigit():
                continue
            if pd.isna(row['CustomerCode']):
                continue

            cust = existing_cust_code_map.get(cust_code)
            if not cust:
                cust = Customer(
                    customer_code=cust_code,
                    salesman=row['Salesman'] if pd.notna(row['Salesman']) else None,
                    total_bought=float(row['Total']) if pd.notna(row['Total']) else 0.0,
                    brand_count=int(row[count_col]) if pd.notna(row[count_col]) else 0,
                )
                session.add(cust)
                session.commit()
                session.refresh(cust)
                inserted_customers += 1
                existing_cust_code_map[cust_code] = cust
            else:
                # Update existing customer fields
                cust.salesman = row['Salesman'] if pd.notna(row['Salesman']) else cust.salesman
                cust.total_bought = float(row['Total']) if pd.notna(row['Total']) else cust.total_bought
                cust.brand_count = int(row[count_col]) if pd.notna(row[count_col]) else cust.brand_count
                session.add(cust)
                session.commit()

            for brand_code in brand_cols:
                amount = row[brand_code]
                if pd.notna(amount) and amount > 0:
                    brand_sale = BrandSale(
                        brand_code=brand_code,
                        amount=float(amount),
                        customer_id=cust.id,
                        purchase_month=purchase_month
                    )
                    session.add(brand_sale)
                    inserted_brand_sales += 1
            session.commit()

        return {
            "message": f"Upload successful for month {purchase_month_str}",
            "inserted_customers": inserted_customers,
            "inserted_brand_sales": inserted_brand_sales,
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Upload failed, see logs")

# API to get customers with optional filtering by salesman or code
@app.get("/customers/", response_model=List[Customer])
def read_customers(
        salesman: Optional[str] = None,
        customer_code: Optional[str] = None,
        session: Session = Depends(get_session),
        offset: int = 0,
        limit: int = Query(default=100, lte=500)
):
    query = select(Customer)
    if salesman:
        query = query.where(Customer.salesman == salesman)
    if customer_code:
        query = query.where(Customer.customer_code == customer_code)
    results = session.exec(query.offset(offset).limit(limit)).all()
    return results

# API to get all brands or sales aggregated by brand (optionally filter by month)
@app.get("/brands/")
def read_brands(
        aggregate: bool = True,
        purchase_month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
        session: Session = Depends(get_session),
        offset: int = 0,
        limit: int = Query(default=100, lte=500)
):
    statement = None
    if purchase_month:
        try:
            pm_date = parse_month_to_date(purchase_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        pm_date = None

    if aggregate:
        stmt = select(BrandSale.brand_code, BrandSale.amount)
        if pm_date:
            stmt = stmt.where(BrandSale.purchase_month == pm_date)
        stmt = stmt.order_by(BrandSale.brand_code)
        results = session.exec(stmt).all()

        from collections import defaultdict
        aggregate_dict = defaultdict(float)
        for brand_code, amount in results:
            aggregate_dict[brand_code] += amount

        items = sorted(aggregate_dict.items(), key=lambda x: x[1], reverse=True)
        items_page = items[offset: offset + limit]

        return [{"brand_code": b, "total_amount": a} for b, a in items_page]

    else:
        stmt = select(BrandSale)
        if pm_date:
            stmt = stmt.where(BrandSale.purchase_month == pm_date)
        stmt = stmt.offset(offset).limit(limit)
        results = session.exec(stmt).all()
        return results

# API to get sales details for a specific customer (optionally filter by month)
@app.get("/customers/{customer_id}/brands")
def get_customer_brand_sales(
        customer_id: int,
        purchase_month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
        session: Session = Depends(get_session)
):
    if purchase_month:
        try:
            pm_date = parse_month_to_date(purchase_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        pm_date = None

    query = select(BrandSale).where(BrandSale.customer_id == customer_id)
    if pm_date:
        query = query.where(BrandSale.purchase_month == pm_date)

    sales = session.exec(query).all()
    return sales

# API to get summary total sales of all customers (optionally filter by month)
@app.get("/summary/total_sales")
def total_sales_summary(
        purchase_month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
        session: Session = Depends(get_session)
):
    if purchase_month:
        try:
            pm_date = parse_month_to_date(purchase_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        pm_date = None

    stmt = select(Customer.total_bought)
    if pm_date:
        # Get customer ids that have sales in the given month
        cust_ids = session.exec(
            select(BrandSale.customer_id).where(BrandSale.purchase_month == pm_date).distinct()
        ).all()
        cust_ids = list(cust_ids)
        stmt = stmt.where(Customer.id.in_(cust_ids))

    totals = session.exec(stmt).all()
    total_sum = sum(totals) if totals else 0.0
    return {"total_sales_all_customers": total_sum}

# API to get top N customers by total bought sales (optionally filter by month)
@app.get("/top-customers/")
def top_customers(
        limit: int = Query(default=10, lte=100),
        purchase_month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
        session: Session = Depends(get_session)
):
    if purchase_month:
        try:
            pm_date = parse_month_to_date(purchase_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        pm_date = None

    if pm_date:
        cust_ids = session.exec(
            select(BrandSale.customer_id).where(BrandSale.purchase_month == pm_date).distinct()
        ).all()
        cust_ids = list(cust_ids)
        if not cust_ids:
            return []
        stmt = select(Customer).where(Customer.id.in_(cust_ids))
    else:
        stmt = select(Customer)

    stmt = stmt.order_by(Customer.total_bought.desc()).limit(limit)
    results = session.exec(stmt).all()
    return results

# API to get top N brands by aggregated sales (optionally filter by month)
@app.get("/top-brands/")
def top_brands(
        limit: int = Query(default=10, lte=100),
        purchase_month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
        session: Session = Depends(get_session)
):
    if purchase_month:
        try:
            pm_date = parse_month_to_date(purchase_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        pm_date = None

    stmt = select(
        BrandSale.brand_code,
        func.sum(BrandSale.amount).label("total_amount")
    )
    if pm_date:
        stmt = stmt.where(BrandSale.purchase_month == pm_date)
    stmt = stmt.group_by(BrandSale.brand_code).order_by(desc("total_amount")).limit(limit)
    results = session.exec(stmt).all()
    response = [{"brand_code": r.brand_code, "total_amount": r.total_amount} for r in results]
    return response
