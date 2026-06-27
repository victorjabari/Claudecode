# STEM Pathway — Industriell ekonomi (Umeå University)

An MVP that maps **what you study → what careers open up → why → and which
courses to take next**. Built around one program to start:
**Civilingenjör i industriell ekonomi** (M.Sc. Industrial Engineering &
Management, 300 hp) at **Umeå University**.

A student picks their specialization, ticks the courses they've completed, and
immediately sees:

1. **Their skills** — derived from the courses they've passed.
2. **What careers fit, and why** — every relevant career ranked by how much of
   it their courses already cover, with a per-skill breakdown of *which of their
   courses feed the role* and *what's still missing*.
3. **Recommended next courses** — ranked by how much they raise career coverage,
   each one stating **why** (which careers it advances, with before→after match)
   and **how** (which new skills it adds).

The two questions the brief asked for are answered everywhere and are always
**derived from the data, never hardcoded**:
- **What** = which careers your courses point to (coverage ranking).
- **Why** = the course → skill → career impact chain, plus the gaps.

## Run it

It's a static site — no build, no install.

```bash
# Option A: just open the file
open stem-pathway/index.html        # macOS  (xdg-open on Linux)

# Option B: serve it (nicer URLs, identical behaviour)
cd stem-pathway && python3 -m http.server 8000
# then visit http://localhost:8000
```

## Test it

Pure-Node tests (engine logic + data integrity), no dependencies:

```bash
cd stem-pathway && node --test tests.js
```

## How it's structured

| File          | Responsibility                                                            |
|---------------|---------------------------------------------------------------------------|
| `data.js`     | Seed domain data: program, specialization tracks, skills, courses, careers |
| `engine.js`   | Pure reasoning: skills → career coverage ranking → course recommendations  |
| `app.js`      | DOM controller: reads inputs, calls the engine, renders results            |
| `index.html`  | Layout                                                                     |
| `styles.css`  | Styling (Umeå blue)                                                        |
| `tests.js`    | `node --test` suite for the engine and data                               |

The **data layer is deliberately separate from the logic** so the next steps are
clean swaps, not rewrites.

### The model

- **Skills** are the shared vocabulary that links courses to careers.
- **Courses** grant skills and are tagged `core` (shared years 1–3) or a track
  id (`risk` / `log` / `ds`) for years 4–5.
- **Careers** *want* skills, each with a weight (1 helpful → 3 core) and a
  one-line note on *how* that skill shows up in the job.
- **Coverage** of a career = weighted fraction of its skills you hold.
- **Recommendations** simulate adding each untaken course and rank by the total
  coverage gain across all track-relevant careers (the mandatory thesis opts out
  via `recommendable: false`).

## Data provenance & honesty

- **Years 1–3** courses follow Umeå University's published *utbildningsplan* for
  the program.
- **Years 4–5** specialization courses (Risk Management, Logistics &
  Optimization, Data Science) are **representative placeholders** — real course
  titles/credits should be replaced from the official *kursplaner*.
- Career skill-weights and outlooks are seed estimates for the MVP, not survey
  data.

Sources:
- <https://www.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi/>
- <https://www2.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi>

## Roadmap (toward the full product)

1. **Replace seed data with official syllabuses.** Parse Umeå's
   *utbildningsplan* / *kursplaner* per faculty into `data.js`'s shape. Each
   kursplan already lists intended learning outcomes → those become `skills`.
2. **Expand beyond one program** to Umeå's wider STEM sector (other
   civilingenjör and kandidat programs) — the `tracks`/`courses` model already
   supports multiple catalogs.
3. **AI-driven job/internship matching.** Swap the static `careers` list for a
   service that pulls live roles and maps each posting's requirements onto the
   same skill vocabulary — the engine's coverage/gap logic then works unchanged.
4. **Accounts & persistence** so students save their progress over a degree.
