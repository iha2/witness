# superlite build report

projection: fixed forecast saved at lint 2026-11-14T18:13:42 (plan edited since)

                         Projected    Actual  Delta
wall-clock (min)               4.3      21.0  +16.7 (+386%)
agent cost (USD, +rework)      2.50      3.31  +0.80 (+32%)
task-minutes                  36.6      37.1  +0.4 (+1%)
agents                          17        25  +8 (+47%)
cost split: agents $3.19, rework $0.11, coordinator $7.00, total $10.30
concurrency: peak 6 at once (projected 10); critical path actual T5 T15; projected T2 > T9 (4.3 min)
model mix: haiku 2 tasks $0.03, sonnet 10 tasks $3.27, coordinator opus $7.00
quality: tests 180 passed, 0 failed; first-time pass n/a; rework dispatches 1; open incidents 190

task  model      pred  actual  delta             cost
T11   sonnet      2.2     5.5  +3.3 (+149%)    $0.521
T5    sonnet      2.2     4.1  +1.9 (+88%)     $0.369
T18   sonnet      2.8     1.1  -1.7 (-62%)     $0.148
T15   sonnet      3.1     4.4  +1.2 (+40%)     $0.715
T17   haiku       1.5     2.6  +1.2 (+80%)     $0.016
(+7 smaller misses; `superlite-cli report --json` lists all)

agent cost table:
| agent | model | wall_min | tokens | usd |
| --- | --- | --- | --- | --- |
| a00c6a8ebe2f8428c | sonnet | 1.0103 | 124875 | 0.0765 |
| a04108ba6bd48ddf4 | haiku | 2.69 | 571460 | 0.016 |
| a3d6c7cee6ea99884 | opus | 0.5422 | 34157 | 0.1884 |
| a407d0aba39c472e4 | sonnet | 29911646.8749 | 0 | 0.0 |
| a43dda34d75f62306 | sonnet | 0.6832 | 199582 | 0.1113 |
| a58f444c060823dba | sonnet | 29911653.9078 | 0 | 0.0 |
| a5dad9c1b4f4c17a5 | haiku | 3.6681 | 378978 | 0.0169 |
| a6a1d97b321490659 | sonnet | 8.7348 | 812913 | 0.5665 |
| a77d919215f7a3fc0 | sonnet | 0.342 | 68696 | 0.0466 |
| a7b197c26f527e5f8 | sonnet | 29911604.9852 | 0 | 0.0 |
| a7ba90ad550ce84a6 | sonnet | 10.087 | 1399695 | 0.6392 |
| a7e2343ac5d9cd610 | sonnet | 5.5363 | 646637 | 0.5215 |
| a886d231839fa4a3b | sonnet | 0.6197 | 77791 | 0.0902 |
| a8b33ad0fc90540a6 | sonnet | 1.3983 | 234527 | 0.1221 |
| a908b12fa2324348f | sonnet | 1.3219 | 209442 | 0.1788 |
| a9ab5722eb067f8d9 | sonnet | 29911639.5135 | 0 | 0.0 |
| a9c559adc0854f302 | sonnet | 1.5962 | 329266 | 0.2248 |
| aadb62e5ba48da2c5 | sonnet | 29911629.6865 | 0 | 0.0 |
| ab3b40f8de3435957 | sonnet | 29911636.5089 | 0 | 0.0 |
| aca296c652bb06142 | sonnet | 8.2382 | 472175 | 0.4059 |
| adacb7009ce215c43 | sonnet | 29911642.6962 | 0 | 0.0 |
| aee4167fe86e30567 | sonnet | 0.8604 | 156234 | 0.1174 |
| af1ad0753b2237dc1 | sonnet | 7.109 | 501119 | 0.384 |
| af2e274bf030075b8 | sonnet | 1.8594 | 492789 | 0.2489 |
| af57a4eaf7bec026f | sonnet | 1.077 | 163490 | 0.1228 |
| totals |  | 209381511.547 | 6873826 | 4.0778 |
cost source: est

trend (last 1 run): first-time pass n/a; findings 2; rework+fixer cost 3%
lessons: 3 cached, 0 proven
takeaway: ran 386% slower than projected; cost 32% over; biggest miss T11
