/*
 * engine.js — The "what & why" reasoning layer.
 *
 * Everything here is pure and deterministic: given the data and a student's
 * completed courses, it derives skills, ranks careers, and recommends courses
 * with explanations. No DOM, no globals beyond the export — so it runs both in
 * the browser and under Node for the tests.
 *
 * Two questions the platform must answer, and where each is computed:
 *   WHAT careers fit me?      -> rankCareers()  (coverage of each career's skills)
 *   WHY do my courses matter? -> each career carries `matched` (your course -> skill
 *                                -> impact) and `gaps` (skills still missing).
 *   ...and for guidance:      -> recommendCourses() ranks UNTAKEN courses by how
 *                                much they raise your career coverage, and says
 *                                which careers (why) and which skills (how).
 */

function buildEngine(DATA) {
  const skillById = DATA.skills;
  const courseById = Object.fromEntries(DATA.courses.map((c) => [c.id, c]));
  const careerById = Object.fromEntries(DATA.careers.map((c) => [c.id, c]));

  // Courses available to a track = shared core courses + that track's courses.
  // The "undecided" track only sees the core (years 1–3 + shared advanced).
  function coursesForField(trackId) {
    return DATA.courses
      .filter((c) => c.tracks.includes(trackId) || c.tracks.includes("core"))
      .sort((a, b) => a.year - b.year || a.name.localeCompare(b.name));
  }

  // Skills a student has, mapped to the courses that granted them.
  // { skillId: [course, course...] }
  function skillsFromCourses(completedIds) {
    const out = {};
    completedIds.forEach((id) => {
      const course = courseById[id];
      if (!course) return;
      course.skills.forEach((s) => {
        (out[s] = out[s] || []).push(course);
      });
    });
    return out;
  }

  // Max coverage a field's whole catalog could give a career. Used to decide
  // which careers are even reachable from a field (so we don't show, say, a
  // pure-biology career to a CS student).
  function fieldCatalogSkills(fieldId) {
    const set = new Set();
    coursesForField(fieldId).forEach((c) => c.skills.forEach((s) => set.add(s)));
    return set;
  }

  // Coverage of a single career given the set of skills the student has.
  // Returns weighted coverage in [0,1] plus the matched/missing breakdown that
  // powers the "why".
  function scoreCareer(career, haveSkills) {
    let total = 0;
    let got = 0;
    const matched = [];
    const gaps = [];
    career.skills.forEach((req) => {
      total += req.weight;
      const have = haveSkills[req.id];
      if (have && have.length) {
        got += req.weight;
        matched.push({
          skillId: req.id,
          skillName: skillById[req.id].name,
          weight: req.weight,
          impact: req.impact,
          viaCourses: have.map((c) => c.name),
        });
      } else {
        gaps.push({
          skillId: req.id,
          skillName: skillById[req.id].name,
          weight: req.weight,
          impact: req.impact,
        });
      }
    });
    // Sort so the most important contributions/gaps lead.
    matched.sort((a, b) => b.weight - a.weight);
    gaps.sort((a, b) => b.weight - a.weight);
    return {
      coverage: total ? got / total : 0,
      weightedGot: got,
      weightedTotal: total,
      matched,
      gaps,
    };
  }

  // How relevant a career is to a field, independent of what's completed yet:
  // weighted fraction of the career's skills the field's catalog can teach.
  function careerFieldRelevance(career, fieldId) {
    const catalog = fieldCatalogSkills(fieldId);
    let total = 0;
    let reachable = 0;
    career.skills.forEach((req) => {
      total += req.weight;
      if (catalog.has(req.id)) reachable += req.weight;
    });
    return total ? reachable / total : 0;
  }

  // WHAT: rank the careers that make sense for this field, scored against the
  // student's completed courses. `relevanceFloor` filters out careers the field
  // can barely touch.
  function rankCareers(fieldId, completedIds, relevanceFloor = 0.34) {
    const haveSkills = skillsFromCourses(completedIds);
    return DATA.careers
      .map((career) => {
        const relevance = careerFieldRelevance(career, fieldId);
        const score = scoreCareer(career, haveSkills);
        return { career, relevance, ...score };
      })
      .filter((r) => r.relevance >= relevanceFloor)
      // Sort by current coverage, then by how relevant the career is to the field.
      .sort((a, b) => b.coverage - a.coverage || b.relevance - a.relevance);
  }

  // HOW/WHY: rank untaken courses by the total improvement they'd make to the
  // student's coverage across all field-relevant careers. Each recommendation
  // explains which careers it advances and which new skills it adds.
  function recommendCourses(fieldId, completedIds, opts = {}) {
    const relevanceFloor = opts.relevanceFloor ?? 0.34;
    const limit = opts.limit ?? 6;
    const completed = new Set(completedIds);
    const haveSkills = skillsFromCourses(completedIds);
    const haveSkillIds = new Set(Object.keys(haveSkills));

    const relevantCareers = DATA.careers.filter(
      (c) => careerFieldRelevance(c, fieldId) >= relevanceFloor
    );

    // Baseline coverage per relevant career.
    const baseline = {};
    relevantCareers.forEach((c) => {
      baseline[c.id] = scoreCareer(c, haveSkills).coverage;
    });

    // Candidates = untaken courses in this track that are meant to be chosen
    // (the mandatory thesis opts out via recommendable: false).
    const candidates = coursesForField(fieldId).filter(
      (c) => !completed.has(c.id) && c.recommendable !== false
    );

    const scored = candidates.map((course) => {
      const newSkills = course.skills.filter((s) => !haveSkillIds.has(s));

      // Simulate having this course's skills too.
      const simulated = { ...haveSkills };
      course.skills.forEach((s) => {
        simulated[s] = (simulated[s] || []).concat(course);
      });

      let totalGain = 0;
      const careerImpacts = [];
      relevantCareers.forEach((career) => {
        const after = scoreCareer(career, simulated).coverage;
        const delta = after - baseline[career.id];
        if (delta > 1e-9) {
          totalGain += delta;
          careerImpacts.push({
            careerId: career.id,
            title: career.title,
            from: baseline[career.id],
            to: after,
            delta,
          });
        }
      });
      careerImpacts.sort((a, b) => b.delta - a.delta);

      return {
        course,
        newSkills: newSkills.map((s) => ({ id: s, name: skillById[s].name })),
        totalGain,
        careerImpacts,
        // gentle tie-break: earlier-year (more foundational) courses first
        year: course.year,
      };
    });

    return scored
      .filter((r) => r.totalGain > 1e-9)
      .sort((a, b) => b.totalGain - a.totalGain || a.year - b.year)
      .slice(0, limit);
  }

  // Flat list of the skills a student currently has (for the summary chips).
  function studentSkills(completedIds) {
    const have = skillsFromCourses(completedIds);
    return Object.keys(have)
      .map((id) => ({
        id,
        name: skillById[id].name,
        category: skillById[id].category,
        viaCourses: have[id].map((c) => c.name),
      }))
      .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
  }

  return {
    coursesForField,
    skillsFromCourses,
    studentSkills,
    scoreCareer,
    careerFieldRelevance,
    rankCareers,
    recommendCourses,
    _internal: { courseById, careerById, skillById },
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { buildEngine };
} else {
  window.buildEngine = buildEngine;
}
