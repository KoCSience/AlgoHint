"""Teacher-only reference solution for the L2 search exercise."""

n, target = map(int, input().split())
values = list(map(int, input().split()))
for index, value in enumerate(values, start=1):
    if value == target:
        print(index)
        break
else:
    print(-1)
