## baseline vs improved

Cases: 17 · judged 2026-09-10T11:10:58 / 2026-09-10T11:07:34

### Headline

| Measure | baseline | improved | |
|---|---|---|---|
| Mean case score | 0.841 | 0.954 | ↑ |
| Fully passing cases | 8/17 | 12/17 | ↑ |
| Mean helpfulness (1-5) | 4.580 | 4.500 | ↓ **regression** |

### Per metric

| Metric | baseline | improved | |
|---|---|---|---|
| `citation_validity` | 94% | 100% | ↑ |
| `has_citation` | 88% | 100% | ↑ |
| `retrieval_recall` | 92% | 100% | ↑ |
| `abstention_correct` | 100% | 100% | = |
| `must_mention` | 100% | 100% | = |
| `must_not_mention` | 100% | 100% | = |
| `intent_correct` | 40% | 100% | ↑ |
| `groundedness` | 76% | 71% | ↓ **regression** |

### Per case type (mean score)

| Case type | baseline | improved | |
|---|---|---|---|
| clarify_previous | 0.785 | 0.928 | ↑ |
| cross_episode_compare | 0.849 | 0.944 | ↑ |
| episode_routing | 0.738 | 0.841 | ↑ |
| locate_audio | 0.167 | 1.000 | ↑ |
| out_of_scope | 0.933 | 1.000 | ↑ |
| passage_qa | 1.000 | 1.000 | = |

### Per case

| Case | baseline | improved | Change | Now failing |
|---|---|---|---|---|
| `compare_entropy_two_senses` | 0.857 | 1.000 | improved ↑ | — |
| `compare_fundamental_limits` | 0.857 | 1.000 | improved ↑ | — |
| `compare_two_einstein_episodes` | 0.833 | 0.833 | same | groundedness |
| `followup_pronoun` | 1.000 | 1.000 | same | — |
| `followup_simplify` | 0.571 | 0.857 | improved ↑ | groundedness |
| `locate_photo51` | 0.167 | 1.000 | improved ↑ | — |
| `oos_higgs` | 1.000 | 1.000 | same | — |
| `oos_plate_tectonics` | 0.800 | 1.000 | improved ↑ | — |
| `oos_superconductivity` | 1.000 | 1.000 | same | — |
| `qa_base_pairing` | 1.000 | 1.000 | same | — |
| `qa_bekenstein_entropy` | 1.000 | 1.000 | same | — |
| `qa_halting_problem` | 1.000 | 1.000 | same | — |
| `qa_shannon_redundancy` | 1.000 | 1.000 | same | — |
| `qa_simultaneity` | 1.000 | 1.000 | same | — |
| `route_beginner_order` | 0.667 | 0.833 | improved ↑ | groundedness |
| `route_curved_spacetime` | 0.833 | 0.833 | same | groundedness |
| `route_entropy` | 0.714 | 0.857 | improved ↑ | groundedness |

**Improved:** `compare_entropy_two_senses`, `compare_fundamental_limits`, `followup_simplify`, `locate_photo51`, `oos_plate_tectonics`, `route_beginner_order`, `route_entropy`

**Regressed:** none

**Still failing in both:** `compare_two_einstein_episodes`, `followup_simplify`, `route_beginner_order`, `route_curved_spacetime`, `route_entropy`

### Cost

- baseline: {'calls': 32, 'in_tokens': 75779, 'out_tokens': 5534, 'embed_texts': 20}
- improved: {'calls': 54, 'in_tokens': 105437, 'out_tokens': 7241, 'embed_texts': 70}