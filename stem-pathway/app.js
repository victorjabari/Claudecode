/*
 * app.js — UI controller. Wires the seed data + engine to the DOM.
 * No framework, no build step: plain DOM APIs over the global STEM_DATA / buildEngine.
 */
(function () {
  const DATA = window.STEM_DATA;
  const engine = window.buildEngine(DATA);

  // --- element refs ---
  const $ = (id) => document.getElementById(id);
  const trackSelect = $("field-select");
  const trackBlurb = $("field-blurb");
  const coursesStep = $("courses-step");
  const courseList = $("course-list");
  const emptyState = $("empty-state");
  const results = $("results");
  const skillsSummary = $("skills-summary");
  const skillsChips = $("skills-chips");
  const careersList = $("careers-list");
  const recsList = $("recs-list");

  // --- state ---
  let trackId = "";
  const completed = new Set();

  // --- helpers ---
  const pct = (x) => Math.round(x * 100);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };

  // --- header / program info ---
  function fillProgram() {
    const p = DATA.program;
    $("program-full").textContent = p.name;
    $("program-uni").textContent = p.university.split(" (")[0];
  }

  // --- step 1: track dropdown ---
  function fillTracks() {
    DATA.tracks.forEach((t) => {
      const opt = el("option");
      opt.value = t.id;
      opt.textContent = t.name;
      trackSelect.appendChild(opt);
    });
  }

  // --- step 2: course checklist grouped by year ---
  function renderCourses() {
    courseList.innerHTML = "";
    const courses = engine.coursesForField(trackId);
    const byYear = {};
    courses.forEach((c) => (byYear[c.year] = byYear[c.year] || []).push(c));

    Object.keys(byYear)
      .sort((a, b) => a - b)
      .forEach((year) => {
        const group = el("div", "year-group");
        group.appendChild(el("h3", null, `Year ${year}`));
        byYear[year].forEach((c) => {
          const label = el("label", "course");
          const cb = el("input");
          cb.type = "checkbox";
          cb.value = c.id;
          cb.checked = completed.has(c.id);
          cb.addEventListener("change", () => {
            cb.checked ? completed.add(c.id) : completed.delete(c.id);
            renderResults();
          });
          const text = el("span");
          text.innerHTML =
            `<span class="c-name">${c.name}</span>` +
            `<span class="c-en">${c.nameEn} · <span class="c-hp">${c.hp} hp</span></span>`;
          label.appendChild(cb);
          label.appendChild(text);
          group.appendChild(label);
        });
        courseList.appendChild(group);
      });
  }

  // --- results: skills, careers, recommendations ---
  function renderResults() {
    renderSkills();
    renderCareers();
    renderRecs();
  }

  function renderSkills() {
    const skills = engine.studentSkills([...completed]);
    skillsChips.innerHTML = "";
    if (!skills.length) {
      skillsSummary.textContent =
        "No courses ticked yet — your skills and matches will appear here as you select courses.";
      return;
    }
    skillsSummary.textContent =
      `${skills.length} skill${skills.length > 1 ? "s" : ""} from ${completed.size} course${completed.size > 1 ? "s" : ""}.`;
    skills.forEach((s) => {
      const chip = el("span", "chip", s.name);
      chip.title = `From: ${s.viaCourses.join(", ")}`;
      skillsChips.appendChild(chip);
    });
  }

  function renderCareers() {
    careersList.innerHTML = "";
    const ranked = engine.rankCareers(trackId, [...completed]);
    if (!ranked.length) {
      careersList.appendChild(
        el("p", "muted", "Select a specialization and some courses to see matching careers.")
      );
      return;
    }
    ranked.forEach((r, i) => {
      const c = r.career;
      const card = el("details", "career");
      if (i === 0) card.open = true; // open the strongest match

      const matchedHtml = r.matched.length
        ? `<ul class="reasons">${r.matched
            .map(
              (m) =>
                `<li><span class="why-skill">${m.skillName}</span> — ${m.impact}` +
                `<span class="via"> (you got this from: ${m.viaCourses.join(", ")})</span></li>`
            )
            .join("")}</ul>`
        : `<p class="muted">None of your completed courses feed this role yet.</p>`;

      const gapsHtml = r.gaps.length
        ? `<ul class="reasons">${r.gaps
            .map(
              (g) =>
                `<li class="gap"><span class="why-skill">${g.skillName}</span> — ${g.impact}</li>`
            )
            .join("")}</ul>`
        : `<p class="muted">You already cover every skill this role asks for. 🎉</p>`;

      card.innerHTML =
        `<summary>` +
        `<span class="c-title">${c.title}</span>` +
        `<span class="c-match"><b>${pct(r.coverage)}%</b> match</span>` +
        `<span class="c-summary">${c.summary}</span>` +
        `<span class="bar"><span style="width:${pct(r.coverage)}%"></span></span>` +
        `</summary>` +
        `<div class="body">` +
        `<p class="meta"><b>Outlook:</b> ${c.outlook}</p>` +
        `<p class="meta"><b>Example roles:</b> ${c.sampleRoles.join(", ")}</p>` +
        `<p class="meta"><b>Internships:</b> ${c.internships.join(", ")}</p>` +
        `<h4>Why your studies fit (what you already cover)</h4>${matchedHtml}` +
        `<h4>What's still missing (your gaps)</h4>${gapsHtml}` +
        `</div>`;

      careersList.appendChild(card);
    });
  }

  function renderRecs() {
    recsList.innerHTML = "";
    const recs = engine.recommendCourses(trackId, [...completed], { limit: 6 });
    if (!recs.length) {
      recsList.appendChild(
        el(
          "p",
          "muted",
          completed.size
            ? "No further courses in this track would change your career coverage — you've covered the high-impact ones."
            : "Tick a few courses (or pick a specialization) to get recommendations."
        )
      );
      return;
    }
    recs.forEach((r) => {
      const c = r.course;
      const skillsTxt = r.newSkills.map((s) => s.name).join(", ");
      const careersTxt = r.careerImpacts
        .slice(0, 3)
        .map(
          (ci) =>
            `${ci.title} <span class="up">${pct(ci.from)}%→${pct(ci.to)}%</span>`
        )
        .join(" · ");

      const card = el("div", "rec");
      card.innerHTML =
        `<div class="r-head">` +
        `<span class="r-title">${c.name} <span class="r-en">(${c.nameEn}, Year ${c.year})</span></span>` +
        `<span class="r-gain">+${pct(r.totalGain)} pts</span>` +
        `</div>` +
        `<p class="r-line"><span class="lbl">How it helps:</span> adds ${skillsTxt}.</p>` +
        `<p class="r-careers"><span class="lbl" style="color:var(--umu-blue-dark)">Why take it:</span> raises ${careersTxt}</p>`;
      recsList.appendChild(card);
    });
  }

  // --- events ---
  trackSelect.addEventListener("change", () => {
    trackId = trackSelect.value;
    const track = DATA.tracks.find((t) => t.id === trackId);
    trackBlurb.textContent = track ? track.blurb : "";
    // keep only completed courses that still exist in this track's catalog
    const valid = new Set(engine.coursesForField(trackId).map((c) => c.id));
    [...completed].forEach((id) => valid.has(id) || completed.delete(id));
    coursesStep.hidden = false;
    emptyState.hidden = true;
    results.hidden = false;
    renderCourses();
    renderResults();
  });

  $("select-all").addEventListener("click", () => {
    engine.coursesForField(trackId).forEach((c) => completed.add(c.id));
    renderCourses();
    renderResults();
  });
  $("clear-all").addEventListener("click", () => {
    completed.clear();
    renderCourses();
    renderResults();
  });

  // --- init ---
  fillProgram();
  fillTracks();
})();
