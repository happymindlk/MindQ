# Psychometric Assessment Platform: Build Specification

**Audience:** Cursor (AI coding agent).
**Source of truth:** two documents from the product owner: *Original Assessments - Questions (Statements)* and *Original Assessments - Scoring Mechanism*. This spec contains only what those documents state (plus arithmetic ranges that follow directly from them).

## 0. Rules for the agent

1. `assessments.json` holds every item, item ID, keying, scale membership, answer key, response scale and test case. **Load it; do not retype items or keys into code.**
2. `assets/icar/` holds the 8 image-based CogniCheck items (Q9–Q16).
3. **If something is not stated in this spec, do not invent it.** Ask the product owner, or implement the minimum and leave a clearly marked `TODO(owner)` comment. This includes: grading leniency for typed answers, percentile/norm tables, score-range descriptions, required-answer rules, autosave/resume behaviour and anything else not written below.
4. Follow the owner's naming exactly: **Personal Initiative Scale**, **CogniCheck**, **Mini-IPIP**.

## 1. The 7 assessments

| id | Name | Category | Items | Time allocation (as written) |
|---|---|---|---|---|
| `ipip_ipc` | IPIP Interpersonal Circumplex (IPIP-IPC) | Behavioral | 32 | 4.30 minutes |
| `personal_initiative` | Personal Initiative Scale | Behavioral | 10 | 2 minutes |
| `sjt` | Situational Judgment Test | Behavioral | 8 | 5 minutes |
| `cognicheck` | CogniCheck | Cognitive | 16 | 15 to 20 minutes |
| `crt` | Cognitive Reflection Test | Cognitive | 3 | 3 minutes, **strictly timed** |
| `mini_ipip` | Mini-IPIP | Personality | 20 | 4 minutes |
| `hexaco_hh` | IPIP-HEXACO Honesty-Humility scale | Personality | 40 | 5.30 minutes |

- Show the time allocation exactly as written. The documents only call the CRT "strictly timed"; they do not describe how any other time allocation is enforced.
- The documents say the Mini-IPIP and HEXACO statements "were jumbled to create the assessment", so those two are presented in a jumbled order. **Score by item ID, never by display position.** The other assessments are presented in the listed order.

## 2. Response formats

**5-point scale** (IPIP-IPC, Mini-IPIP, HEXACO): 1 Very Inaccurate, 2 Moderately Inaccurate, 3 Neither Inaccurate nor Accurate, 4 Moderately Accurate, 5 Very Accurate.

**7-point scale** (Personal Initiative Scale): 1 Totally Disagree, 2 Disagree, 3 Moderately Disagree, 4 Neither disagree or agree, 5 Moderately Agree, 6 Agree, 7 Totally Agree.

**Reverse scoring** (Mini-IPIP and HEXACO only): a response of 5 becomes 1, 4 becomes 2, 3 stays 3, 2 becomes 4, 1 becomes 5 (that is, `6 − response`).

**Other formats:** SJT and CogniCheck are single-choice A–D questions; the CRT is an open-ended, fill-in-the-blank test with **no multiple-choice options**.

## 3. Scoring

### 3.1 IPIP-IPC
- Each question rated 1–5. Add the scores for the four questions in each subscale. Each subscale ranges 4–20. Higher scores indicate stronger representation of the characteristics measured by that subscale.

| Subscale | Statements |
|---|---|
| PA: Assured-Dominant | 6, 14, 22, 30 |
| BC: Arrogant-Calculating | 7, 15, 23, 31 |
| DE: Cold-Hearted | 8, 16, 24, 32 |
| FG: Aloof-Introverted | 1, 9, 17, 25 |
| HI: Unassured-Submissive | 2, 10, 18, 26 |
| JK: Unassuming-Ingenuous | 3, 11, 19, 27 |
| LM: Warm-Agreeable | 4, 12, 20, 28 |
| NO: Gregarious-Extraverted | 5, 13, 21, 29 |

### 3.2 Personal Initiative Scale
- All items are positively keyed; there are no reverse-scored items.
- Final score = the **sum or the mean** of all 10 item responses (the document allows either). Store both: sum (10–70) and mean (1–7). Which one is shown is not specified in the documents. `TODO(owner)`.
- Interpretation (as written): higher total scores indicate a stronger proactive personality disposition.

### 3.3 Situational Judgment Test
- Best = 3, Good = 2, Poor = 1, Worst = 0. Total = sum of the 8 item scores, range 0–24.
- Bands: 20–24 consistently strong judgment; 15–19 generally sound; 10–14 mixed; below 10 frequently chose weaker responses.
- Answer key:

| Question | Best | Good | Poor | Worst |
|---|---|---|---|---|
| 1. Pace and quality (Decision making / Pace) | B | C | D | A |
| 2. Rule adherence | B | D | A | C |
| 3. Teamwork | B | D | A | C |
| 4. Decision making under limited authority | C | B | D | A |
| 5. Influence and communication | B | A | C | D |
| 6. Prioritization (Pace) | C | D | A | B |
| 7. Integrity and rules | C | B | D | A |
| 8. Adapting to change (Rule adherence / Decision making) | B | C | D | A |

### 3.4 CogniCheck
- Dichotomous: 1 point for a correct answer, 0 for an incorrect one. Total = sum (16 items, range 0–16).
- Interpretation (as written): higher total scores indicate higher general cognitive ability.
- The questions cover four logic areas: Verbal Reasoning (1–4), Letter and Number Series (5–8), Matrix Reasoning (9–12), Three-Dimensional Rotation (13–16). **The documents state these must not be reported as standalone scores.** Do not output per-area scores in any report, API or export.
- Answer key:

| Q | Key | Q | Key | Q | Key | Q | Key |
|---|---|---|---|---|---|---|---|
| 1 | B | 5 | C | 9 | B | 13 | C |
| 2 | C | 6 | C | 10 | C | 14 | A |
| 3 | D | 7 | B | 11 | A | 15 | D |
| 4 | A | 8 | C | 12 | D | 16 | B |

### 3.5 Cognitive Reflection Test
- Open-ended, fill-in-the-blank. Points are only awarded for the mathematically correct, reflective answer: 1 point for correct, 0 for incorrect. Total range 0–3.
- Interpretation (as written): higher total scores indicate a strong capacity for cognitive reflection, impulse control and analytical thinking.
- Correct answers as written: **Q1: 5 cents (or $0.05)**; **Q2: 5 minutes**; **Q3: 47 days**.
- The documents do not say how typed variants (for example "5" or "five minutes") are treated. Keep the matching logic in one function and mark it `TODO(owner)`.

### 3.6 Mini-IPIP
- 20 statements; both positively keyed (+) and reverse-scored (−) items. Responses for the 4 items in each facet are added together to create the facet score (after reversing − items). Each facet ranges 4–20.
- Interpretation (as written): higher final totals indicate a stronger presence of that personality trait.
- The documents also say scores are "typically standardized into percentiles using global reference norms", but **no norm data is provided**. Do not implement percentiles; return raw facet scores. `TODO(owner)` if norms are supplied later.

| Facet | + keyed | − keyed |
|---|---|---|
| Surgency or Extraversion | 1, 11 | 6, 16 |
| Agreeableness | 2, 12 | 7, 17 |
| Conscientiousness | 3, 13 | 8, 18 |
| Neuroticism | 4, 14 | 9, 19 |
| Intellect or Imagination | 5 | 10, 15, 20 |

### 3.7 IPIP-HEXACO Honesty-Humility
- 40 statements, 10 per facet; both + and − keyed items. Facet score = the 10 items **added or averaged** (after reversing − items); the document allows either, so store both (facet sum 10–50, facet mean 1–5). The overall Honesty-Humility domain score combines all 40 answers: store the sum (40–200) and the mean (1–5).
- Interpretation (as written): higher final numbers indicate high integrity, fairness and an unassuming style; low scores point toward status-seeking, greedy or manipulative behavior.

| Facet | + keyed | − keyed |
|---|---|---|
| Sincerity (H:Sinc) | 1 | 5, 9, 13, 17, 21, 25, 29, 33, 37 |
| Fairness (H:Fair) | 2, 10, 14, 22, 26 | 6, 18, 30, 34, 38 |
| Greed Avoidance (H:Gree) | 11, 23 | 3, 7, 15, 19, 27, 31, 35, 39 |
| Modesty (H:Mode) | 4, 12, 20, 24 | 8, 16, 28, 32, 36, 40 |

## 4. Reporting

Report only the scores defined in section 3 with the interpretation sentences given there. The documents do not define report layouts, score-range descriptions for CogniCheck, or percentile conversions. `TODO(owner)` for any of these.

## 5. Tests

- Load `assessments.json` and run each `testVectors` entry through the scoring function; assert the expected values.
- At load time assert: IPIP-IPC 32 items with 8 subscales of 4; Personal Initiative 10 items; SJT 8 questions each with one option per tier; CogniCheck 16 items (4 per area) and 8 image files present; CRT 3 items; Mini-IPIP 20 items with facets of 4; HEXACO 40 items with facets of 10 and the +/− counts in section 3.7 (1/9, 5/5, 2/8, 4/6).

## 6. Build order

1. Data loading and the scoring function; all test vectors pass.
2. Assessment runner per response format (5-point, 7-point, single-choice text, single-choice image, free-text), with the CRT strictly timed at 3 minutes and jumbled order for Mini-IPIP and HEXACO.
3. Score output exactly as in section 3, with the CogniCheck per-area rule respected.
