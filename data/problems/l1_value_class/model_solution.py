"""Teacher-only reference solution for the L1 classification exercise."""

t = int(input())
if t < 0:
    print("cold")
elif t <= 30:
    print("mild")
else:
    print("hot")
