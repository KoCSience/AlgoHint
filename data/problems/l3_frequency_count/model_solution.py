"""Teacher-only reference solution for the L3 counting exercise."""

n = int(input())
values = map(int, input().split())
counts = {}
pairs = 0
for value in values:
    pairs += counts.get(value, 0)
    counts[value] = counts.get(value, 0) + 1
print(pairs)
