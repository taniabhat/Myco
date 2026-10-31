# Order Pricing Service Requirements

1. apply_discount(price, percent) must raise ValueError if price is negative.
2. apply_discount must raise ValueError if percent is below 0 or above 100.
3. apply_discount must return a float rounded to 2 decimal places.
4. calculate_total(items) must sum price * quantity for each item and return a float rounded to 2 decimals.
5. calculate_total must raise ValueError if any quantity is not a positive integer.
6. format_receipt(order) must use calculate_total and apply_discount from the pricing module, and return a string.
7. An empty items list must return 0.0.
