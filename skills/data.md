---
name: data
description: Data analysis, SQL, pandas, spreadsheets, visualisation
triggers: data, sql, query, database, pandas, dataframe, csv, excel, chart, graph, analyse, analyze, statistics, stats, tableau, plot, matplotlib, seaborn, dataset, spreadsheet
---

# Data Analysis

## SQL

- `SELECT` only the columns you need — never `SELECT *` in production
- Always alias tables in joins: `FROM users u JOIN orders o ON u.id = o.user_id`
- Filter early: `WHERE` before `GROUP BY`, reduces rows processed
- Use CTEs (`WITH`) for readability over nested subqueries
- Index columns used in `WHERE`, `JOIN ON`, and `ORDER BY`

```sql
-- Good pattern
WITH active_users AS (
  SELECT id, name FROM users WHERE status = 'active'
)
SELECT u.name, COUNT(o.id) as order_count
FROM active_users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name
ORDER BY order_count DESC;
```

## Python / pandas

```python
import pandas as pd

df = pd.read_csv('data.csv')

# Always check the data first
print(df.shape)
print(df.dtypes)
print(df.isnull().sum())
print(df.describe())

# Clean before analyze
df = df.dropna(subset=['important_col'])
df['date'] = pd.to_datetime(df['date'])

# Group and aggregate
result = df.groupby('category').agg(
    total=('amount', 'sum'),
    count=('id', 'count'),
    avg=('amount', 'mean')
).reset_index()
```

## Visualization

- Title says what the chart shows, not what it is ("Revenue grew 40% YoY" not "Revenue Chart")
- X-axis = time or categories, Y-axis = the metric
- Bar chart for comparisons, line chart for trends, scatter for correlations
- Label the axes with units
- Don't use pie charts with more than 4 slices

## Reporting findings

- Lead with the insight, not the methodology: "Users aged 25–34 convert 3× better than average"
- Show the data that supports it
- State confidence and limitations honestly
- Suggest the next question to answer
