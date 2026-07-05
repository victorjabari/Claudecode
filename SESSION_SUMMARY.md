# Session Summary — Building **Spår**, a study-to-career platform for Umeå University

*A thorough record of everything we went through in this chat, from the first idea
to a working, tested, and shipped MVP.*

---

## 1. What you asked for

You wanted a platform for **STEM students** that answers, in plain terms:

1. **What do you study?** — pick your program / specialization.
2. **What courses have you completed?** — tick them off.
3. **What career opportunities does that open up?** — the *what*.
4. **How do your studies impact those opportunities?** — the *why*.
5. **What should you take next?** — course recommendations that each explain
   **why** (which careers they advance) and **how** (which skills they add).

Two words you stressed as the heart of the product: **what** and **why**.

You framed it explicitly as an **MVP**, with a clear roadmap beyond it:

> "I am later going to download official campus syllabuses for different faculties
> and pair it with AI-driven job and career and internship finders."

### The pivot that shaped everything

Mid-build you redirected the whole thing (you said it twice, to make sure it stuck):

> "Focus on Umeå university's STEM sector, specifically **civilingenjör i industriell
> ekonomi**."

So we stopped building a generic STEM tool and rebuilt it around **one real program**:
**Civilingenjör i industriell ekonomi** (M.Sc. Industrial Engineering & Management,
300 hp / 5 years) at **Umeå University** — using its *actual* published curriculum,
not invented courses.

---

## 2. What we built

A **zero-build static web app** — no bundler, no framework, no `npm install` to run
it. You can literally double-click `index.html`. It also runs under Node for tests.

### The user flow
1. Choose a **specialization track** (Undecided, Risk Management, Logistics &
   Optimization, or Data Science).
2. **Tick completed courses**, grouped by year.
3. Instantly see:
   - **Your skills so far** (derived from your courses — never hardcoded).
   - **What careers fit — and why**: each relevant career ranked by how much of it
     your courses already cover, with a per-skill breakdown of *which of your
     courses feed the role* and *what's still missing*.
   - **Recommended next courses**: ranked by how much they raise your coverage, each
     stating **why** (which careers, with a before→after match %) and **how**
     (which new skills it adds).

### The core idea that makes it work
**Skills are the shared vocabulary** that links courses to careers:

```
course  --grants-->  skills  <--wants (weighted)--  career
```

- A **course** grants skills and is tagged `core` (shared years 1–3) or a track id
  (`risk` / `log` / `ds`) for the years 4–5 specialization.
- A **career** *wants* skills, each with a weight (1 = helpful → 3 = core) and a
  one-line note on how that skill shows up in the job.
- **Coverage** of a career = the weighted fraction of its wanted skills you hold.
- **Recommendations** simulate adding each untaken course and rank by the total
  coverage gain across all track-relevant careers.

Because everything is derived from data, the "what" and "why" are always honest —
they fall out of the course→skill→career graph rather than being written by hand.

---

## 3. The name — **Spår**

You asked for "a good name." We landed on **Spår** (Swedish for *track / path*):

- It's the **track** you choose (your specialization) **and** the career **path** it
  leads to — one word doing both jobs.
- It's Swedish, which fits an Umeå-University product.
- Tagline: **"from courses to careers."**

The repo folder stays `stem-pathway/` (renaming it would have churned the diff), but
the product, README, and page title are all branded **Spår**.

---

## 4. Files & structure

Everything lives under `stem-pathway/`. The data layer is deliberately kept separate
from the logic so the roadmap steps are clean swaps, not rewrites.

| File          | Responsibility                                                              |
|---------------|-----------------------------------------------------------------------------|
| `data.js`     | Seed domain data: program, specialization tracks, skills, courses, careers  |
| `engine.js`   | Pure reasoning: skills → career coverage ranking → course recommendations   |
| `app.js`      | DOM controller: reads inputs, calls the engine, renders results             |
| `index.html`  | Layout                                                                       |
| `styles.css`  | Styling (Umeå blue, `#0057a4`)                                               |
| `tests.js`    | `node --test` suite for the engine and data                                 |
| `README.md`   | How to run, structure, model, data provenance, roadmap                       |

**Two design choices that matter:**
- **Plain `<script>` tags** (no ES modules) so `index.html` opens straight from
  `file://` with no server.
- **Dual export** in `data.js`/`engine.js` (`window.*` in the browser,
  `module.exports` under Node) so the *same code* powers both the UI and the tests.

---

## 5. The data model (what's real vs. representative)

We were careful to be honest about provenance:

- **Years 1–3 courses** follow Umeå's published *utbildningsplan* for the program —
  real course names and credits (Programmering i Python, Endimensionell analys 1 & 2,
  Linjär algebra, Statistik för teknologer, Stokastiska processer och simulering,
  Linjärprogrammering, Kontinuerlig optimering, Finansiering för ingenjörer,
  Matematisk modellering, Projektledning, Affärsutveckling och innovation, …).
- **Years 4–5 specialization courses** (Risk Management, Logistics & Optimization,
  Data Science) are **representative placeholders**, clearly flagged as such — to be
  swapped for the exact *kursplaner* later.
- **Careers** (~a handful incl. Data Scientist, Risk Analyst, and logistics/
  optimization roles) with skill-weights and outlooks are **seed estimates** for the
  MVP, not survey data.

Skills (~38) are categorized (maths, programming, data, finance/economics,
optimization, business/leadership, …).

Sources noted in the README:
- <https://www.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi/>

---

## 6. The engine (where "what" and "why" are computed)

`engine.js` exposes `buildEngine(DATA)`, which returns pure, deterministic functions:

- `coursesForField(trackId)` — core courses + that track's courses, sorted by year.
- `skillsFromCourses(completedIds)` — `{ skillId: [courses that granted it] }`.
- `scoreCareer(career, haveSkills)` — weighted coverage in `[0,1]`, plus the
  `matched` (your course → skill → impact) and `gaps` (still-missing skills) that
  power the "why."
- `careerFieldRelevance(career, fieldId)` — how much of a career a field could ever
  teach (so we don't show a career the track can't touch).
- `rankCareers(fieldId, completedIds, relevanceFloor = 0.34)` — **the "what."**
- `recommendCourses(fieldId, completedIds, {relevanceFloor, limit})` — **the "how/
  why."** Simulates adding each untaken, *recommendable* course and ranks by total
  coverage gain across relevant careers.

---

## 7. Testing

Pure-Node tests, **no dependencies** (`node:test` + `node:assert`). Run with:

```bash
cd stem-pathway && node --test tests.js
```

**12 tests, all green.** They cover:
- Data integrity (every referenced skill exists; ids are unique).
- `coursesForField` track behavior (a track sees core + its own; undecided sees core
  only; no cross-track leakage).
- `skillsFromCourses` mapping.
- `scoreCareer` monotonicity (coverage only rises as you add relevant courses).
- `rankCareers`: a Data Science student surfaces **Data Scientist** near the top; a
  Risk student's risk career outranks a DS-only one.
- `recommendCourses`: positive & explained gain, never re-recommends a completed
  course, respects the limit, and **never suggests the thesis**.

---

## 8. Bugs we hit and fixed along the way

- **Stray duplicate `data_viz` entry** in the Data Scientist career (weight 0, empty
  impact) → removed.
- **`node --test` found 0 tests** — the file didn't match the default glob → run it
  explicitly as `node --test tests.js`.
- **Playwright smoke test `ERR_MODULE_NOT_FOUND`** — Playwright is installed globally,
  not in the local project, and `executablePath` pointed at a directory → fixed by
  requiring the global absolute path in a `.cjs` script and letting
  `PLAYWRIGHT_BROWSERS_PATH` resolve Chromium.
- **The thesis (Examensarbete) showed up as the #1 recommendation** — misleading,
  since it's a mandatory capstone, not an elective. → Added `recommendable: false`
  to the thesis course, filtered it out of `recommendCourses`, and added a test to
  lock that in.

---

## 9. How to run it

**The app (no install):**
```bash
# Option A — just open the file
open stem-pathway/index.html          # macOS  (xdg-open on Linux)

# Option B — serve it (nicer URLs, identical behaviour)
cd stem-pathway && python3 -m http.server 8000
# then visit http://localhost:8000
```

**The tests (needs Node 18+):**
```bash
cd stem-pathway && node --test tests.js
```

To get the code on your machine, clone the repo and check out the branch
`claude/stem-career-pathway-mvp-00gco0`.

---

## 10. What shipped (Git & PR)

- All work lives on branch **`claude/stem-career-pathway-mvp-00gco0`**.
- Opened **Pull Request #1**, titled *"Spår — STEM study-to-career platform
  (Umeå · Civilingenjör i industriell ekonomi)"*.
- The PR diff is clean — only the `stem-pathway/` files (the unrelated
  `quantum_alpha/` project in the repo was left untouched).
- No CI is configured on the repo, and there were no review threads, so nothing was
  blocking.
- The PR is **being watched** so review comments / CI events get picked up
  automatically.

---

## 11. Roadmap (toward the full product)

1. **Replace seed data with official syllabuses.** Parse Umeå's *utbildningsplan* /
   *kursplaner* per faculty into `data.js`'s shape. Each kursplan already lists
   intended learning outcomes → those become `skills`.
2. **Expand beyond one program** to Umeå's wider STEM sector (other civilingenjör and
   kandidat programs) — the tracks/courses model already supports multiple catalogs.
3. **AI-driven job/internship matching.** Swap the static careers list for a service
   that pulls live roles and maps each posting's requirements onto the same skill
   vocabulary — the engine's coverage/gap logic then works unchanged.
4. **Accounts & persistence** so students save progress across a whole degree.

---

## 12. Open options you can pick up next

- Flesh out the **years 4–5 courses** with exact kursplan data (titles, credits,
  learning outcomes).
- Add **another Umeå program** to prove the multi-catalog model.
- Add a **one-command launcher** (`run.sh` / npm script).
- **Merge PR #1** once you're happy with it.

---

*Built as an MVP: rule-based recommendations over honest seed data for one Umeå
University program — structured so the next steps are swaps, not rewrites.*
