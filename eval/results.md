# Benchmark results (gemini-flash-lite-latest)

35 tasks. A task counts as passed only when the final code passes the visible tests and the hidden tests the assistant never saw.

| Metric | Value |
|---|---|
| Pass rate, first try | 88.6% |
| Pass rate, with self-repair (up to 3 repairs) | 94.3% |
| Visible tests passed, first try / with repair | 88.6% / 100.0% |
| Model calls (mean per task) | 40 (1.14) |
| Tokens (mean per task) | 30095 (860) |
| Model latency per task, mean / median | 2.2 s / 1.87 s |

Pass rate by attempt budget: 1 attempt: 88.6%, 2 attempts: 91.4%, 3 attempts: 94.3%, 4 attempts: 94.3%

| Task | Mode | Attempts | First try | Final | Tokens | Model latency (s) |
|---|---|---|---|---|---|---|
| slugify | generate | 1 | pass | pass | 514 | 1.909 |
| roman_to_int | generate | 1 | pass | pass | 636 | 2.119 |
| merge_intervals | generate | 1 | pass | pass | 406 | 1.425 |
| parse_duration | generate | 2 | fail | pass | 2916 | 4.927 |
| chunk_text | generate | 1 | pass | pass | 627 | 2.07 |
| top_k_words | generate | 1 | pass | pass | 492 | 1.661 |
| luhn_valid | generate | 1 | pass | pass | 399 | 1.463 |
| flatten_dict | generate | 1 | pass | pass | 579 | 2.092 |
| business_days | generate | 1 | pass | pass | 543 | 1.873 |
| rle_encode | generate | 1 | pass | pass | 407 | 1.39 |
| semver_compare | generate | 1 | pass | pass | 1301 | 2.877 |
| spiral_order | generate | 1 | pass | pass | 490 | 1.597 |
| balanced | generate | 1 | pass | pass | 475 | 1.877 |
| split_csv_line | generate | 1 | pass | pass | 623 | 1.955 |
| humanize_bytes | generate | 1 | pass | pass | 450 | 1.289 |
| lru_cache | generate | 1 | pass | pass | 539 | 1.74 |
| number_to_words | generate | 1 | pass | pass | 808 | 2.006 |
| next_permutation | generate | 1 | pass | pass | 520 | 1.547 |
| moving_average | generate | 1 | pass | pass | 454 | 1.31 |
| topo_sort | generate | 1 | pass | pass | 642 | 2.349 |
| evaluate_expression | generate | 2 | fail | fail | 3770 | 6.215 |
| justify | generate | 1 | pass | pass | 819 | 2.252 |
| wildcard_match | generate | 1 | pass | pass | 1178 | 3.329 |
| title_case | generate | 1 | pass | pass | 837 | 2.023 |
| osa_distance | generate | 1 | pass | pass | 636 | 1.772 |
| format_table | generate | 1 | pass | pass | 1266 | 3.42 |
| natural_sort | generate | 2 | fail | fail | 1452 | 3.274 |
| parse_query | generate | 3 | fail | pass | 3213 | 6.377 |
| compress_ranges | generate | 1 | pass | pass | 455 | 1.322 |
| fix_binary_search | fix | 1 | pass | pass | 532 | 1.723 |
| fix_average | fix | 1 | pass | pass | 336 | 1.215 |
| fix_palindrome | fix | 1 | pass | pass | 301 | 0.992 |
| fix_fizzbuzz | fix | 1 | pass | pass | 529 | 1.118 |
| fix_days_in_month | fix | 1 | pass | pass | 478 | 1.157 |
| fix_word_count | fix | 1 | pass | pass | 472 | 1.448 |
