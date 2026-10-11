# Measures

Generated from `tools/generate.py`. All measures live on the `Orders` table, grouped in display folders.

## Order Count

*Sales* · format `#,0` · Orders placed.

```dax
Order Count =
COUNTROWS ( Orders )
```

## Revenue

*Sales* · format `"R$"#,0` · Value of goods sold, excluding freight (Brazilian reais).

```dax
Revenue =
SUM ( 'Order Items'[price] )
```

## Freight

*Sales* · format `"R$"#,0` · Freight charged to customers.

```dax
Freight =
SUM ( 'Order Items'[freight_value] )
```

## Avg Order Value

*Sales* · format `"R$"#,0.00` · Revenue per order.

```dax
Avg Order Value =
DIVIDE ( [Revenue], [Order Count] )
```

## Customer Count

*Sales* · format `#,0` · Distinct people who ordered.

```dax
Customer Count =
DISTINCTCOUNT ( Orders[customer_unique_id] )
```

## Revenue LY

*Sales* · format `"R$"#,0` · Revenue in the same period a year earlier.

```dax
Revenue LY =
CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( 'Calendar'[date_day] ) )
```

## Revenue YoY %

*Sales* · format `0.0%;-0.0%;0.0%` · Change in revenue against the same period a year earlier.

```dax
Revenue YoY % =
VAR _ly = [Revenue LY]
RETURN
    IF ( NOT ISBLANK ( _ly ), DIVIDE ( [Revenue] - _ly, _ly ) )
```

## Revenue Running Total

*Sales* · format `"R$"#,0` · Cumulative revenue up to the latest date in context.

```dax
Revenue Running Total =
CALCULATE (
    [Revenue],
    FILTER ( ALL ( 'Calendar'[date_day] ), 'Calendar'[date_day] <= MAX ( 'Calendar'[date_day] ) )
)
```

## Delivered Orders

*Delivery* · format `#,0` · Orders delivered, with a delivery date recorded.

```dax
Delivered Orders =
CALCULATE (
    COUNTROWS ( Orders ),
    Orders[order_status] = "delivered",
    NOT ISBLANK ( Orders[delivered_at] )
)
```

## Late Orders

*Delivery* · format `#,0` · Delivered after the date promised at checkout.

```dax
Late Orders =
CALCULATE ( [Delivered Orders], Orders[is_late] == TRUE () )
```

## % Late

*Delivery* · format `0.0%` · Share of delivered orders that arrived late.

```dax
% Late =
DIVIDE ( [Late Orders], [Delivered Orders] )
```

## Avg Delivery Days

*Delivery* · format `0.0` · Days from purchase to delivery.

```dax
Avg Delivery Days =
CALCULATE ( AVERAGE ( Orders[delivery_days] ), Orders[order_status] = "delivered" )
```

## Avg Review

*Reviews* · format `0.00` · Average review score, 1 to 5.

```dax
Avg Review =
AVERAGE ( Orders[review_score] )
```

## Avg Review (On Time)

*Reviews* · format `0.00` · Average review for orders delivered on or before the promised date.

```dax
Avg Review (On Time) =
CALCULATE ( [Avg Review], Orders[is_late] == FALSE () )
```

## Avg Review (Late)

*Reviews* · format `0.00` · Average review for orders delivered late.

```dax
Avg Review (Late) =
CALCULATE ( [Avg Review], Orders[is_late] == TRUE () )
```

## Review Gap

*Reviews* · format `0.00` · How many stars a late delivery costs.

```dax
Review Gap =
[Avg Review (On Time)] - [Avg Review (Late)]
```

## % One-Star

*Reviews* · format `0.0%` · Share of reviewed orders rated one star.

```dax
% One-Star =
DIVIDE (
    CALCULATE ( COUNTROWS ( Orders ), Orders[review_score] = 1 ),
    CALCULATE ( COUNTROWS ( Orders ), NOT ISBLANK ( Orders[review_score] ) )
)
```

## Repeat Customer %

*Customers* · format `0.0%` · Share of customers who ordered more than once.

```dax
Repeat Customer % =
DIVIDE (
    CALCULATE ( COUNTROWS ( Customers ), Customers[is_repeat_customer] == TRUE () ),
    COUNTROWS ( Customers )
)
```
