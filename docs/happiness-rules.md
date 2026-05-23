# Happiness Rules

The first scoring engine is deterministic and explainable. ML can help classify ticket formats later, but happiness itself should stay transparent.

## Degrees

- Степень 0: обычная искра, заметные, но частые узоры.
- Степень 1: счастливые номера, например равные суммы половинок.
- Степень 2: очень счастливые редкие визуальные или зеркальные узоры.
- Степень 3: легендарные математические и культурные находки.

## Seed Examples

- `0303`: degree 0, repeated halves.
- `0312`: degree 1, `0 + 3 = 1 + 2`.
- `0889`: степень 1, мягко счастливый: слева `0 + 8 = 8`, справа `8 + 9 = 17`, `1 + 7 = 8`.
- `0898`: степень 2, редкий выбранный узор.
- `0369`: степень 3, арифметическая прогрессия `0, 3, 6, 9`.

## Curated Dictionary

Some values should be added by hand because they are culturally or mathematically meaningful:

- arithmetic sequences;
- Ramanujan/Hardy style numbers;
- local memes;
- dates or city-specific numbers;
- product community favorites.
