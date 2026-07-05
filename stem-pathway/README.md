# Spår — from courses to careers

> **Spår** is Swedish for *track / path* — both the specialization **track** you
> choose and the career **path** it leads to. (Folder kept as `stem-pathway/`.)

A platform that maps **what you study → what careers open up → why → and which
courses to take next**. Built around one program to start:
**Civilingenjör i industriell ekonomi** (M.Sc. Industrial Engineering &
Management, 300 hp) at **Umeå University** — architected so the same catalog
shape scales to every Umeå faculty, then other universities, then education
beyond STEM.

A student picks their specialization, ticks the courses they've completed, and
immediately sees:

1. **What you carry** — skills derived from the courses they've passed.
2. **Destinations — what fits, and why** — every relevant career ranked by how
   much of it their courses already cover, with a per-skill breakdown of *which
   of their courses feed the role* and *what's still missing*.
3. **Next stations** — course recommendations ranked by how much they raise
   career coverage, each stating **why** (which careers it advances, with
   before→after match) and **how** (which new skills it adds).

The two core questions are answered everywhere and are always **derived from the
data, never hardcoded**:
- **What** = which careers your courses point to (coverage ranking).
- **Why** = the course → skill → career impact chain, plus the gaps.

## Run it

It's a static site — no build, no install.

```bash
# Option A: just open the file
open stem-pathway/index.html        # macOS  (xdg-open on Linux)

# Option B: serve it (enables offline + install-as-app)
cd stem-pathway && python3 -m http.server 8000
# then visit http://localhost:8000
```

**Use it as an app:** served over http(s) it's an installable PWA — "Add to
Home Screen" on a phone, "Install" in Chrome/Edge on desktop. It works offline
after the first visit, and your track + completed courses are saved on-device
(localStorage; nothing leaves the browser). A native wrapper (Capacitor) is the
later step; the app shell is already in place.

> Deploy note: `sw.js` is cache-first — **bump the `CACHE` version string** in
> `sw.js` whenever any shipped file changes.

## Test it

Pure-Node tests (engine logic + data integrity + catalog contract), no
dependencies:

```bash
cd stem-pathway && node --test tests.js
```

## How it's structured

| File                   | Responsibility                                                             |
|------------------------|-----------------------------------------------------------------------------|
| `data.js`              | Catalog: program, specialization tracks, skills, courses, careers          |
| `engine.js`            | Pure reasoning: skills → career coverage ranking → course recommendations  |
| `app.js`               | DOM controller + on-device persistence                                     |
| `index.html`           | Layout + service-worker registration                                       |
| `styles.css`           | "Paper & rail" design system (see below)                                   |
| `tests.js`             | `node --test` suite: engine, data, and catalog contract                    |
| `manifest.webmanifest` | PWA manifest (installable app)                                             |
| `sw.js`                | Offline app shell (cache-first, versioned)                                 |
| `icon.svg`             | App icon: the rail line with stations                                      |

The **data layer is deliberately separate from the logic** so the roadmap steps
are data drops, not rewrites.

### The model

- **Skills** are the shared vocabulary that links courses to careers.
- **Courses** grant skills and are tagged `core` (shared years 1–3) or a track
  id (`risk` / `log` / `ds`) for years 4–5. Each course MAY carry
  `syllabus: { url }` pointing at its official kursplan — the UI links it
  automatically and tests enforce https. This is the slot the future
  syllabus-ingest pipeline fills.
- **Careers** *want* skills, each with a weight (1 helpful → 3 core) and a
  one-line note on *how* that skill shows up in the job.
- **Coverage** of a career = weighted fraction of its skills you hold.
- **Recommendations** simulate adding each untaken course and rank by the total
  coverage gain across all track-relevant careers (the mandatory thesis opts out
  via `recommendable: false`).

### The design — "paper & rail"

Deliberately editorial rather than app-template: warm paper ground, near-black
ink, hairline rules instead of card shadows, serif display type, mono for
numbers, marker-yellow highlights — and one brand motif carried everywhere,
the **rail line** (Spår = track): the course list runs on a rail with year
"stations", careers are **destinations**, recommendations are numbered **next
stations**, and the icon is the line itself. Zero webfonts, zero images, zero
external requests — fast everywhere and safe under any CSP.

## Data provenance & honesty

- **Years 1–3** courses follow Umeå University's published *utbildningsplan* for
  the program.
- **Years 4–5** specialization courses (Risk Management, Logistics &
  Optimization, Data Science) are **representative placeholders** — real course
  titles/credits should be replaced from the official *kursplaner*.
- Career skill-weights and outlooks are seed estimates for the MVP, not survey
  data.
- Per-course `syllabus.url` links are only added once verified against the
  official source — **never guessed** (test-enforced shape).

Sources:
- <https://www.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi/>
- <https://www2.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi>

## Roadmap (toward the full product)

Expansion happens in rings, and each ring is a **data drop into the same
catalog shape** — the engine and UI don't change:

1. **Official syllabuses for this program.** Fill every course's
   `syllabus: { url }` from Umeå's kursplaner; refine skills from each
   kursplan's intended learning outcomes.
2. **Umeå's STEM sector** — the other civilingenjör and kandidat programs.
3. **All Umeå faculties**, then **other universities** (each is one more
   catalog: program + tracks + courses + skills).
4. **Beyond STEM — every education**, so anyone can find a career with this.
5. **AI-driven job/internship matching.** Swap the static `careers` list for a
   service that pulls live roles and maps each posting's requirements onto the
   same skill vocabulary — the engine's coverage/gap logic then works unchanged.
6. **Native app wrapper** (Capacitor) over the existing PWA shell, and accounts
   so progress syncs across devices.
