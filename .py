def apply_discount(price, percent=10):
    discount = price * percent / 100
    return price - discount

a = apply_discount(200)
b = apply_discount(a, 50)
c = apply_discount(percent=25, price=80)
print(a, b, c)