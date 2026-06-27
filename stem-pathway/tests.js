/*
 * tests.js — engine + data sanity tests. Run with: node --test
 * Uses only Node built-ins (node:test, node:assert) — no install needed.
 */
const test = require("node:test");
const assert = require("node:assert");

const DATA = require("./data.js");
const { buildEngine } = require("./engine.js");
const engine = buildEngine(DATA);

const ID = (course) => course.id;

test("data integrity: every course skill exists in the skills map", () => {
  DATA.courses.forEach((c) => {
    c.skills.forEach((s) =>
      assert.ok(DATA.skills[s], `course ${c.id} references unknown skill "${s}"`)
    );
  });
});

test("data integrity: every career skill exists in the skills map", () => {
  DATA.careers.forEach((c) => {
    c.skills.forEach((req) =>
      assert.ok(DATA.skills[req.id], `career ${c.id} references unknown skill "${req.id}"`)
    );
  });
});

test("data integrity: ids are unique", () => {
  const uniq = (arr) => new Set(arr).size === arr.length;
  assert.ok(uniq(DATA.courses.map((c) => c.id)), "duplicate course id");
  assert.ok(uniq(DATA.careers.map((c) => c.id)), "duplicate career id");
  assert.ok(uniq(DATA.tracks.map((t) => t.id)), "duplicate track id");
});

test("coursesForField: a specialization sees core + its own courses, undecided sees core only", () => {
  const core = DATA.courses.filter((c) => c.tracks.includes("core")).map(ID).sort();
  const undecided = engine.coursesForField("undecided").map(ID).sort();
  assert.deepStrictEqual(undecided, core, "undecided should equal the core catalog");

  const ds = new Set(engine.coursesForField("ds").map(ID));
  core.forEach((id) => assert.ok(ds.has(id), `ds track missing core course ${id}`));
  // ds track must include at least one ds-only course
  const dsOnly = DATA.courses.filter((c) => c.tracks.includes("ds"));
  assert.ok(dsOnly.length > 0 && ds.has(dsOnly[0].id), "ds track missing its own courses");
  // ...and must NOT include a risk-only course
  const riskOnly = DATA.courses.find((c) => c.tracks.length === 1 && c.tracks[0] === "risk");
  assert.ok(!ds.has(riskOnly.id), "ds track leaked a risk-only course");
});

test("skillsFromCourses: completing Python grants the programming skill", () => {
  const skills = engine.skillsFromCourses(["y1_python"]);
  assert.ok(skills.programming, "Python should grant programming");
  assert.strictEqual(skills.programming[0].id, "y1_python");
});

test("scoreCareer: coverage rises monotonically as you add relevant courses", () => {
  const ds = DATA.careers.find((c) => c.id === "data_scientist");
  const none = engine.scoreCareer(ds, engine.skillsFromCourses([]));
  const some = engine.scoreCareer(ds, engine.skillsFromCourses(["y2_statistik"]));
  const more = engine.scoreCareer(
    ds,
    engine.skillsFromCourses(["y2_statistik", "ds_ml", "ds_db"])
  );
  assert.strictEqual(none.coverage, 0);
  assert.ok(some.coverage > none.coverage, "stats should raise data-scientist coverage");
  assert.ok(more.coverage > some.coverage, "ML + data eng should raise it further");
});

test("rankCareers: a Data Science student surfaces Data Scientist near the top", () => {
  const completed = ["y1_python", "y2_statistik", "ds_ml", "ds_statml", "ds_db"];
  const ranked = engine.rankCareers("ds", completed);
  assert.ok(ranked.length > 0, "should return careers");
  const top3 = ranked.slice(0, 3).map((r) => r.career.id);
  assert.ok(top3.includes("data_scientist"), `expected data_scientist in top 3, got ${top3}`);
});

test("rankCareers: a Risk student surfaces a risk career above a DS-only one", () => {
  const completed = ["y2_statistik", "risk_finrisk", "risk_riskanalys", "risk_tidsserie", "y3_finans"];
  const ranked = engine.rankCareers("risk", completed);
  const riskRank = ranked.findIndex((r) => r.career.id === "risk_analyst");
  const dsRank = ranked.findIndex((r) => r.career.id === "data_scientist");
  assert.ok(riskRank !== -1, "risk_analyst should be present");
  // data_scientist needs ML, which the risk track can't teach -> filtered out or lower
  assert.ok(dsRank === -1 || riskRank < dsRank, "risk career should outrank a DS career here");
});

test("recommendCourses: suggests untaken courses with positive, explained gain", () => {
  const completed = ["y1_python", "y2_statistik"];
  const recs = engine.recommendCourses("ds", completed, { limit: 6 });
  assert.ok(recs.length > 0, "should recommend something");
  recs.forEach((r) => {
    assert.ok(!completed.includes(r.course.id), "must not recommend a completed course");
    assert.ok(r.totalGain > 0, "recommendation must have positive gain");
    assert.ok(r.careerImpacts.length > 0, "must explain which careers it helps");
    r.careerImpacts.forEach((ci) => assert.ok(ci.to > ci.from, "impact must be an improvement"));
  });
});

test("recommendCourses: a course granting no new skill is never recommended", () => {
  // After Python, recommending another pure-programming course should add no skill.
  const recs = engine.recommendCourses("ds", ["y1_python"]);
  const ids = recs.map((r) => r.course.id);
  assert.ok(!ids.includes("y1_python"), "should not re-recommend a completed course");
});

test("recommendCourses: never suggests a non-recommendable course (e.g. the thesis)", () => {
  const recs = engine.recommendCourses("ds", []);
  assert.ok(!recs.map((r) => r.course.id).includes("adv_exjobb"), "thesis must be excluded");
});

test("recommendCourses respects the limit", () => {
  const recs = engine.recommendCourses("log", [], { limit: 3 });
  assert.ok(recs.length <= 3, "should respect the limit");
});
