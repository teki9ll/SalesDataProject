# SalesDataProject: Setup and Usage Guide

This documentation explains how to set up and run the [SalesDataProject](https://github.com/teki9ll/SalesDataProject.git), upload your own sales data (e.g., for June 2025), and use the API endpoints to query your data.

***

## 1. **Clone the Repository**

```bash
git clone https://github.com/teki9ll/SalesDataProject.git
cd SalesDataProject
```


***

## 2. **Install Python Dependencies**

It’s highly recommended to use a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate    # or on Linux source venv/bin/activate
```

Install requirements:

```bash
pip install -r requirements.txt
```


***

## 3. **Project Structure Overview**

- `main.py` — Main FastAPI application (your API server)
- `requirements.txt` — All dependencies listed here
- `sales_data.db` — SQLite database created automatically after upload
- (your data file) — e.g., `pharma_june_2025.xlsx`

***

## 4. **Run the API Server**

From inside the project folder:

```bash
uvicorn app:app --reload
```

The server will run at: [http://127.0.0.1:8000](http://127.0.0.1:8000)

***

## 5. **Upload Your Own Data** (Year: 2025-06)

To add your customer sales data:

- Ensure your Excel file follows the expected format (headers start at Row 5; columns: CustomerCode, Salesman, Total, [brand columns...], [count column])
- Place your file in the project directory, e.g., `pharma_june_2025.xlsx`


### Using `curl`:

```bash
curl -X POST "http://127.0.0.1:8000/upload-month-data/" \
     -F purchase_month_str=2025-06 \
     -F file=@pharma_june_2025.xlsx
```


### Or use the API documentation UI:

1. Go to [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
2. Find **POST /upload-month-data/**
3. Enter `2025-06` for `purchase_month_str`
4. Choose your file (`pharma_june_2025.xlsx`)
5. Execute

***

## 6. **Query Your Data via the API**

Once uploaded, you can use the following endpoints:


| Endpoint | Description | Example (2025-06) |
| :-- | :-- | :-- |
| `GET /customers/` | List all customers | `/customers/` |
| `GET /brands/` | List brands, aggregated sales | `/brands/?aggregate=true&purchase_month=2025-06` |
| `GET /brands/` | Detailed brand sales (per entry) | `/brands/?aggregate=false&purchase_month=2025-06` |
| `GET /customers/{id}/brands` | Brand sales for a customer | `/customers/1/brands?purchase_month=2025-06` |
| `GET /summary/total_sales` | Total sales for all customers | `/summary/total_sales?purchase_month=2025-06` |
| `GET /top-customers/` | Top customers by total bought | `/top-customers/?limit=10&purchase_month=2025-06` |
| `GET /top-brands/` | Top selling brands | `/top-brands/?limit=10&purchase_month=2025-06` |

All API endpoints can be tested interactively via the `/docs` Swagger UI:

- Browse to [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

***

## 7. **Iterate and Improve**

- This project is a **prototype**. You can enhance it by:
    - Adding authentication.
    - Adding customer/brand metadata management.
    - Supporting more complex analytics or reports.
    - Improving Excel import usability or validation.

***

## **Summary**

- Clone the repo, install dependencies, and start the server.
- Upload your own Excel data using the provided API.
- Query, analyze, and explore your data immediately using the flexible endpoints and the automatic documentation UI.
- Adjust or enhance the project as needed to better fit your real-world pharma sales analysis needs.

**For further improvements and contributions, refer to the repository’s README and open issues or pull requests as needed.**

[^1]: https://github.com/teki9ll/SalesDataProject.git

