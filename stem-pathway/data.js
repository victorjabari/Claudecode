/*
 * data.js — Seed domain data for the STEM Pathway MVP.
 *
 * FOCUS: Umeå University, STEM sector — specifically the
 * Civilingenjörsprogrammet i industriell ekonomi (Industrial Engineering &
 * Management, 300 hp / 5 years).
 *
 * This is the layer you will later replace with parsed OFFICIAL Umeå syllabuses
 * (utbildningsplan/kursplaner per faculty) and live data from AI-driven
 * job/internship finders. The shape is deliberately explicit so that swap is easy:
 *
 *   program  — the degree this MVP is built around
 *   tracks   — the specialization a student is in / aiming for (years 4–5)
 *   skills   — the shared vocabulary linking courses to careers
 *   courses  — real program courses (Swedish names kept; that's how students know
 *              them); each grants skills, and is tagged with the track(s) it
 *              belongs to ("core" = shared years 1–3)
 *   careers  — opportunities I-engineers ("I-are") actually go into; each WANTS
 *              skills (with a weight) and explains HOW that skill shows up in the job
 *
 * The "what / why" the platform answers is DERIVED, never hardcoded:
 *   what  = which careers your completed courses point to (ranked by coverage)
 *   why   = which of YOUR courses -> skills feed each career, and which gaps remain
 *
 * Curriculum sourced from Umeå University's program pages (see meta.sources).
 * Years 1–3 courses follow the published utbildningsplan; the years 4–5
 * specialization courses are representative placeholders to be replaced with the
 * official kursplaner — see README.
 *
 * Works in the browser (window.STEM_DATA) and in Node (module.exports).
 */

const PROGRAM = {
  id: "civ_ie",
  name: "Civilingenjör i industriell ekonomi",
  nameEn: "M.Sc. in Industrial Engineering & Management",
  university: "Umeå University (Umeå universitet)",
  faculty: "Faculty of Science and Technology (Teknisk-naturvetenskaplig fakultet)",
  credits: "300 hp",
  years: 5,
  blurb:
    "Sweden's broad civilingenjör degree that fuses engineering mathematics, " +
    "computing and optimization with economics, finance and leadership. " +
    'Graduates ("I-are") are hired as the bridge between technical and business sides.',
};

// The specialization a student is in or aiming for. "undecided" = still in the
// shared core years (1–3) and hasn't chosen a track yet.
const TRACKS = [
  {
    id: "undecided",
    name: "Years 1–3 · core (specialization undecided)",
    blurb: "Shared foundation. Pick a specialization later to unlock more career paths.",
  },
  {
    id: "risk",
    name: "Specialization · Risk Management (Riskhantering)",
    blurb: "Financial risk, insurance/actuarial maths, time series and decision analysis.",
  },
  {
    id: "log",
    name: "Specialization · Logistics & Optimization (Logistik & optimering)",
    blurb: "Supply chains, production planning, operations research and simulation.",
  },
  {
    id: "ds",
    name: "Specialization · Data Science",
    blurb: "Machine learning, statistical learning, data engineering and large-scale analysis.",
  },
];

const SKILLS = {
  // --- Quantitative & computing ---
  calculus:            { name: "Calculus (en/flervariabelanalys)", category: "Quantitative" },
  linear_algebra:      { name: "Linear Algebra", category: "Quantitative" },
  statistics:          { name: "Statistics", category: "Quantitative" },
  stochastics:         { name: "Stochastic Processes & Simulation", category: "Quantitative" },
  optimization:        { name: "Optimization (LP & nonlinear)", category: "Quantitative" },
  math_modeling:       { name: "Mathematical Modelling", category: "Quantitative" },
  programming:         { name: "Programming (Python)", category: "Computing" },
  algorithms:          { name: "Data Structures & Algorithms", category: "Computing" },
  machine_learning:    { name: "Machine Learning", category: "Computing" },
  data_eng:            { name: "Databases & Data Engineering", category: "Computing" },
  deep_learning:       { name: "Deep Learning", category: "Computing" },
  statistical_learning:{ name: "Statistical Machine Learning", category: "Computing" },
  big_data:            { name: "Large-scale Data Analysis", category: "Computing" },

  // --- Economics & business ---
  industrial_economics:{ name: "Industrial Economics", category: "Economics & Business" },
  economics:           { name: "Economic Theory (micro/macro)", category: "Economics & Business" },
  marketing:           { name: "Marketing", category: "Economics & Business" },
  finance:             { name: "Finance & Investment", category: "Economics & Business" },
  cost_accounting:     { name: "Costing & Financial Control", category: "Economics & Business" },
  business_dev:        { name: "Business Development & Innovation", category: "Economics & Business" },
  entrepreneurship:    { name: "Entrepreneurship", category: "Economics & Business" },
  economic_history:    { name: "Industrial & Economic History", category: "Economics & Business" },

  // --- Management & professional ---
  leadership:          { name: "Organisation & Leadership", category: "Management & Professional" },
  project_mgmt:        { name: "Project Management", category: "Management & Professional" },
  quality_mgmt:        { name: "Quality Management (Lean/Six Sigma)", category: "Management & Professional" },
  sustainability:      { name: "Sustainable Development", category: "Management & Professional" },
  professional_role:   { name: "Engineering Professional Practice", category: "Management & Professional" },
  industrial_design:   { name: "Industrial Design", category: "Management & Professional" },
  communication:       { name: "Technical Communication", category: "Management & Professional" },

  // --- Track: Risk Management ---
  risk_management:     { name: "Risk Analysis & Management", category: "Risk" },
  financial_risk:      { name: "Financial Risk", category: "Risk" },
  time_series:         { name: "Time Series Analysis", category: "Risk" },
  actuarial:           { name: "Insurance & Actuarial Mathematics", category: "Risk" },
  decision_analysis:   { name: "Decision Analysis", category: "Risk" },

  // --- Track: Logistics & Optimization ---
  supply_chain:        { name: "Supply Chain Management", category: "Logistics & Optimization" },
  logistics:           { name: "Logistics", category: "Logistics & Optimization" },
  production:          { name: "Production Planning", category: "Logistics & Optimization" },
  operations_research: { name: "Operations Research", category: "Logistics & Optimization" },
  simulation_modeling: { name: "Simulation Modelling", category: "Logistics & Optimization" },
};

/*
 * Courses. `year` 1–5, `hp` = Swedish higher-ed credits (60 hp = one year).
 * `tracks`: ["core"] for the shared years 1–3, or the specialization id for
 * years 4–5 courses. A "core" course is offered to every track.
 */
const COURSES = [
  // ---------- Year 1 (core) ----------
  { id: "y1_intro_ie",   year: 1, hp: 7.5, tracks: ["core"], name: "Introduktion till industriell ekonomi", nameEn: "Introduction to Industrial Economics", skills: ["industrial_economics", "professional_role"], desc: "What the I-engineer role is and the industrial-economics toolkit." },
  { id: "y1_python",     year: 1, hp: 7.5, tracks: ["core"], name: "Programmering i Python", nameEn: "Programming in Python", skills: ["programming"], desc: "First programming course: variables, control flow, functions." },
  { id: "y1_analys1",    year: 1, hp: 7.5, tracks: ["core"], name: "Endimensionell analys 1", nameEn: "Single-variable Calculus 1", skills: ["calculus"], desc: "Limits, derivatives, integrals." },
  { id: "y1_analys2",    year: 1, hp: 7.5, tracks: ["core"], name: "Endimensionell analys 2", nameEn: "Single-variable Calculus 2", skills: ["calculus"], desc: "Series, techniques of integration, applications." },
  { id: "y1_linalg",     year: 1, hp: 7.5, tracks: ["core"], name: "Linjär algebra", nameEn: "Linear Algebra", skills: ["linear_algebra"], desc: "Vectors, matrices, linear systems and transformations." },
  { id: "y1_marknad",    year: 1, hp: 7.5, tracks: ["core"], name: "Marknadsföring för ingenjörer", nameEn: "Marketing for Engineers", skills: ["marketing"], desc: "Markets, customers, and positioning for technical products." },
  { id: "y1_ekteori",    year: 1, hp: 7.5, tracks: ["core"], name: "Ekonomisk teori och marknadsorganisation", nameEn: "Economic Theory & Market Organisation", skills: ["economics"], desc: "Micro/macro foundations and how markets are organised." },
  { id: "y1_indutv",     year: 1, hp: 7.5, tracks: ["core"], name: "Industriell utveckling och ekonomisk förändring", nameEn: "Industrial Development & Economic Change", skills: ["economic_history"], desc: "How industry and economies evolve over time." },

  // ---------- Year 2 (core) ----------
  { id: "y2_statistik",  year: 2, hp: 7.5, tracks: ["core"], name: "Statistik för teknologer", nameEn: "Statistics for Engineers", skills: ["statistics"], desc: "Probability, estimation, hypothesis testing, regression." },
  { id: "y2_stokast",    year: 2, hp: 7.5, tracks: ["core"], name: "Stokastiska processer och simulering", nameEn: "Stochastic Processes & Simulation", skills: ["stochastics", "statistics"], desc: "Markov processes, queues, and Monte-Carlo simulation." },
  { id: "y2_linprog",    year: 2, hp: 7.5, tracks: ["core"], name: "Linjärprogrammering", nameEn: "Linear Programming", skills: ["optimization"], desc: "Formulating and solving linear optimization problems." },
  { id: "y2_ledarskap",  year: 2, hp: 7.5, tracks: ["core"], name: "Organisation och ledarskap i arbetslivet", nameEn: "Organisation & Leadership", skills: ["leadership"], desc: "How organisations work and how to lead teams." },
  { id: "y2_flervar",    year: 2, hp: 7.5, tracks: ["core"], name: "Flervariabelanalys och differentialekvationer", nameEn: "Multivariable Calculus & Differential Equations", skills: ["calculus"], desc: "Partial derivatives, multiple integrals, ODEs." },
  { id: "y2_dsa",        year: 2, hp: 7.5, tracks: ["core"], name: "Datastrukturer och algoritmer", nameEn: "Data Structures & Algorithms", skills: ["algorithms", "programming"], desc: "Core data structures, complexity, and algorithm design." },
  { id: "y2_ingrol",     year: 2, hp: 7.5, tracks: ["core"], name: "Ingenjörens roll i arbetslivet", nameEn: "The Engineer's Professional Role", skills: ["professional_role", "communication"], desc: "Professional practice, ethics, and communication." },
  { id: "y2_hallbar",    year: 2, hp: 7.5, tracks: ["core"], name: "Hållbar utveckling för ingenjörer", nameEn: "Sustainable Development for Engineers", skills: ["sustainability"], desc: "Environmental, social, and economic sustainability." },

  // ---------- Year 3 (core) ----------
  { id: "y3_kvalitet",   year: 3, hp: 7.5, tracks: ["core"], name: "Strategier och verktyg för kvalitetsarbete", nameEn: "Quality Strategies & Tools", skills: ["quality_mgmt"], desc: "Lean, Six Sigma, and continuous-improvement methods." },
  { id: "y3_kontopt",    year: 3, hp: 7.5, tracks: ["core"], name: "Kontinuerlig optimering", nameEn: "Continuous (Nonlinear) Optimization", skills: ["optimization", "math_modeling"], desc: "Nonlinear and constrained optimization methods." },
  { id: "y3_finans",     year: 3, hp: 7.5, tracks: ["core"], name: "Finansiering för ingenjörer", nameEn: "Finance for Engineers", skills: ["finance", "cost_accounting"], desc: "Investment appraisal, costing, and financial control." },
  { id: "y3_matmod",     year: 3, hp: 7.5, tracks: ["core"], name: "Matematisk modellering", nameEn: "Mathematical Modelling", skills: ["math_modeling", "optimization"], desc: "Turning real problems into solvable mathematical models." },
  { id: "y3_projekt",    year: 3, hp: 7.5, tracks: ["core"], name: "Projektledning", nameEn: "Project Management", skills: ["project_mgmt", "leadership"], desc: "Planning, scope, risk, and delivering projects." },
  { id: "y3_affar",      year: 3, hp: 7.5, tracks: ["core"], name: "Affärsutveckling och innovation", nameEn: "Business Development & Innovation", skills: ["business_dev", "entrepreneurship"], desc: "Building new business and bringing innovation to market." },
  { id: "y3_inddesign",  year: 3, hp: 7.5, tracks: ["core"], name: "Industriell design", nameEn: "Industrial Design", skills: ["industrial_design"], desc: "Designing products and processes for users and industry." },

  // ---------- Years 4–5 · shared advanced ----------
  { id: "adv_finansiell",year: 4, hp: 7.5, tracks: ["core"], name: "Finansiell ekonomi", nameEn: "Financial Economics / Management", skills: ["finance", "financial_risk"], desc: "Asset pricing, portfolios, and corporate finance." },
  { id: "adv_exjobb",    year: 5, hp: 30,  tracks: ["core"], recommendable: false, name: "Examensarbete", nameEn: "Master's Thesis", skills: ["math_modeling", "communication", "project_mgmt"], desc: "Independent applied research project, 30 hp (mandatory capstone, not an elective)." },

  // ---------- Track: Risk Management (years 4–5) ----------
  { id: "risk_riskanalys", year: 4, hp: 7.5, tracks: ["risk"], name: "Riskanalys och riskhantering", nameEn: "Risk Analysis & Management", skills: ["risk_management", "decision_analysis"], desc: "Identifying, quantifying, and managing risk." },
  { id: "risk_finrisk",    year: 4, hp: 7.5, tracks: ["risk"], name: "Finansiell riskhantering", nameEn: "Financial Risk Management", skills: ["financial_risk", "finance"], desc: "Market, credit, and liquidity risk; VaR and hedging." },
  { id: "risk_tidsserie",  year: 4, hp: 7.5, tracks: ["risk"], name: "Tidsserieanalys", nameEn: "Time Series Analysis", skills: ["time_series", "statistics"], desc: "Forecasting and modelling data over time." },
  { id: "risk_forsakring", year: 5, hp: 7.5, tracks: ["risk"], name: "Försäkringsmatematik", nameEn: "Insurance / Actuarial Mathematics", skills: ["actuarial", "stochastics"], desc: "Pricing and reserving for insurance and pensions." },
  { id: "risk_beslut",     year: 5, hp: 7.5, tracks: ["risk"], name: "Beslutsanalys", nameEn: "Decision Analysis", skills: ["decision_analysis", "optimization"], desc: "Structured decision-making under uncertainty." },

  // ---------- Track: Logistics & Optimization (years 4–5) ----------
  { id: "log_opt",       year: 4, hp: 7.5, tracks: ["log"], name: "Optimeringslära", nameEn: "Advanced Optimization", skills: ["optimization", "operations_research"], desc: "Integer, network, and large-scale optimization." },
  { id: "log_scm",       year: 4, hp: 7.5, tracks: ["log"], name: "Supply chain management", nameEn: "Supply Chain Management", skills: ["supply_chain", "logistics"], desc: "Designing and running end-to-end supply chains." },
  { id: "log_prod",      year: 4, hp: 7.5, tracks: ["log"], name: "Produktionsplanering", nameEn: "Production Planning & Control", skills: ["production", "logistics"], desc: "Planning, scheduling, and controlling production." },
  { id: "log_or",        year: 5, hp: 7.5, tracks: ["log"], name: "Operationsanalys", nameEn: "Operations Research", skills: ["operations_research", "optimization"], desc: "Analytical methods for operational decisions." },
  { id: "log_sim",       year: 5, hp: 7.5, tracks: ["log"], name: "Simulering av system", nameEn: "Systems Simulation", skills: ["simulation_modeling", "stochastics"], desc: "Discrete-event simulation of logistics systems." },

  // ---------- Track: Data Science (years 4–5) ----------
  { id: "ds_ml",         year: 4, hp: 7.5, tracks: ["ds"], name: "Maskininlärning", nameEn: "Machine Learning", skills: ["machine_learning", "statistical_learning"], desc: "Supervised/unsupervised learning and model evaluation." },
  { id: "ds_statml",     year: 4, hp: 7.5, tracks: ["ds"], name: "Statistisk maskininlärning", nameEn: "Statistical Machine Learning", skills: ["statistical_learning", "statistics"], desc: "The statistical foundations behind ML models." },
  { id: "ds_db",         year: 4, hp: 7.5, tracks: ["ds"], name: "Databaser och datahantering", nameEn: "Databases & Data Engineering", skills: ["data_eng", "programming"], desc: "Relational modeling, SQL, and data pipelines." },
  { id: "ds_dl",         year: 5, hp: 7.5, tracks: ["ds"], name: "Djupinlärning", nameEn: "Deep Learning", skills: ["deep_learning", "machine_learning"], desc: "Neural networks for vision, language, and more." },
  { id: "ds_bigdata",    year: 5, hp: 7.5, tracks: ["ds"], name: "Storskalig dataanalys", nameEn: "Large-scale Data Analysis", skills: ["big_data", "data_eng"], desc: "Tools and methods for analysing big data." },
];

/*
 * Careers I-engineers actually move into. Each lists the skills it draws on with
 * a weight (1 = helpful, 2 = important, 3 = core) and a one-line `impact`
 * describing HOW that skill shows up in the job. Relevance to a track is computed
 * from skill overlap with that track's catalog — not hardcoded — so choosing a
 * specialization naturally surfaces new opportunities.
 */
const CAREERS = [
  {
    id: "consultant",
    title: "Management Consultant",
    summary: "Solve strategy, operations, and organisation problems for client companies.",
    outlook: "A classic destination for I-engineers; strong demand at firms of every size.",
    sampleRoles: ["Strategy Consultant", "Operations Consultant", "Associate"],
    internships: ["Summer Associate", "Consulting Intern"],
    skills: [
      { id: "business_dev",   weight: 3, impact: "Framing and solving business problems is the whole job." },
      { id: "economics",      weight: 2, impact: "You reason about markets, costs, and incentives daily." },
      { id: "project_mgmt",   weight: 2, impact: "Engagements are projects you scope and drive." },
      { id: "leadership",     weight: 2, impact: "You lead workshops and align stakeholders." },
      { id: "communication",  weight: 2, impact: "Recommendations only land if you can present them." },
      { id: "finance",        weight: 1, impact: "Business cases rest on financial reasoning." },
    ],
  },
  {
    id: "business_analyst",
    title: "Business / Financial Analyst",
    summary: "Turn data and financials into decisions for a company or investor.",
    outlook: "Broad, accessible entry role across industry and finance.",
    sampleRoles: ["Business Analyst", "Financial Analyst", "Investment Analyst"],
    internships: ["Finance Intern", "Business Analyst Intern"],
    skills: [
      { id: "finance",        weight: 3, impact: "You build and read the financial models." },
      { id: "cost_accounting",weight: 2, impact: "Costing and control are the language of the role." },
      { id: "statistics",     weight: 2, impact: "You analyse data to back up recommendations." },
      { id: "economics",      weight: 2, impact: "Market context shapes every analysis." },
      { id: "communication",  weight: 1, impact: "You translate numbers for decision-makers." },
    ],
  },
  {
    id: "project_manager",
    title: "Project / Program Manager",
    summary: "Plan, coordinate, and deliver complex technical projects on time and budget.",
    outlook: "Needed everywhere; a natural fit for the I-engineer profile.",
    sampleRoles: ["Project Manager", "Program Manager", "Project Engineer"],
    internships: ["Project Coordination Intern", "PMO Intern"],
    skills: [
      { id: "project_mgmt",  weight: 3, impact: "Planning, scope, and delivery are the core skill." },
      { id: "leadership",    weight: 3, impact: "You align and motivate cross-functional teams." },
      { id: "cost_accounting", weight: 2, impact: "You own budgets and track spend." },
      { id: "risk_management", weight: 1, impact: "Managing project risk keeps delivery on track." },
      { id: "communication", weight: 2, impact: "Stakeholder updates are constant." },
    ],
  },
  {
    id: "supply_chain",
    title: "Supply Chain / Logistics Manager",
    summary: "Design and run the flow of goods from suppliers to customers efficiently.",
    outlook: "Growing with global trade complexity and resilience demands.",
    sampleRoles: ["Supply Chain Analyst", "Logistics Manager", "Demand Planner"],
    internships: ["Supply Chain Intern", "Logistics Intern"],
    skills: [
      { id: "supply_chain",        weight: 3, impact: "Designing the supply network is the role itself." },
      { id: "logistics",          weight: 3, impact: "Moving and storing goods well is the daily work." },
      { id: "optimization",       weight: 2, impact: "Routing and inventory are optimization problems." },
      { id: "operations_research",weight: 2, impact: "Analytical models drive the big decisions." },
      { id: "production",         weight: 1, impact: "Supply must sync with production plans." },
    ],
  },
  {
    id: "operations",
    title: "Operations / Production Manager",
    summary: "Make production and operations efficient, repeatable, and high quality.",
    outlook: "Core role in manufacturing and service operations.",
    sampleRoles: ["Operations Manager", "Production Manager", "Continuous Improvement Lead"],
    internships: ["Operations Intern", "Lean / CI Intern"],
    skills: [
      { id: "production",   weight: 3, impact: "You plan and control how output is produced." },
      { id: "quality_mgmt", weight: 3, impact: "Lean/Six Sigma is how you raise quality and cut waste." },
      { id: "logistics",    weight: 2, impact: "Material flow feeds the operation." },
      { id: "leadership",   weight: 2, impact: "You run the team on the floor." },
      { id: "optimization", weight: 1, impact: "Scheduling and capacity are optimization problems." },
    ],
  },
  {
    id: "or_analyst",
    title: "Operations Research / Optimization Analyst",
    summary: "Build mathematical models that optimise pricing, routing, scheduling, and capacity.",
    outlook: "Valued wherever decisions can be modelled and optimised at scale.",
    sampleRoles: ["OR Analyst", "Optimization Engineer", "Decision Scientist"],
    internships: ["Operations Research Intern", "Optimization Intern"],
    skills: [
      { id: "operations_research", weight: 3, impact: "OR methods are the core of the job." },
      { id: "optimization",        weight: 3, impact: "You formulate and solve optimization models." },
      { id: "math_modeling",       weight: 2, impact: "Real problems must be turned into models." },
      { id: "programming",         weight: 2, impact: "Models are implemented and run in code." },
      { id: "simulation_modeling", weight: 1, impact: "Simulation validates and stress-tests solutions." },
    ],
  },
  {
    id: "data_scientist",
    title: "Data Scientist",
    summary: "Answer business and research questions with statistics, ML, and clear analysis.",
    outlook: "Strong demand wherever decisions are data-driven.",
    sampleRoles: ["Data Scientist", "Decision Scientist", "Analytics Specialist"],
    internships: ["Data Science Intern", "Analytics Intern"],
    skills: [
      { id: "machine_learning",    weight: 3, impact: "Predictive models are a routine tool." },
      { id: "statistics",          weight: 3, impact: "Sound inference separates analysis from guessing." },
      { id: "programming",         weight: 2, impact: "You script analyses and automate reporting." },
      { id: "statistical_learning",weight: 2, impact: "Understanding model assumptions avoids bad calls." },
      { id: "data_eng",            weight: 2, impact: "Most of the work is getting data analysis-ready." },
      { id: "big_data",            weight: 1, impact: "Scale changes which methods are feasible." },
    ],
  },
  {
    id: "mle",
    title: "Machine Learning Engineer",
    summary: "Turn models into reliable, production-grade systems that learn from data.",
    outlook: "Fast-growing; sits between software and ML.",
    sampleRoles: ["ML Engineer", "Applied Scientist", "MLOps Engineer"],
    internships: ["ML Engineering Intern", "Applied ML Intern"],
    skills: [
      { id: "machine_learning", weight: 3, impact: "Choosing and training the right models is core." },
      { id: "programming",      weight: 3, impact: "ML systems are software, not just notebooks." },
      { id: "deep_learning",    weight: 2, impact: "Vision/NLP roles lean on neural networks." },
      { id: "data_eng",         weight: 2, impact: "You build the pipelines that feed models." },
      { id: "linear_algebra",   weight: 1, impact: "Models are matrix math; you debug at that level." },
      { id: "big_data",         weight: 1, impact: "Training and serving at scale needs big-data tooling." },
    ],
  },
  {
    id: "risk_analyst",
    title: "Quantitative Risk Analyst / Risk Manager",
    summary: "Measure and manage financial and operational risk for banks, insurers, and firms.",
    outlook: "Steady demand, heavily regulated, well paid.",
    sampleRoles: ["Risk Analyst", "Market Risk Manager", "Credit Risk Analyst"],
    internships: ["Risk Management Intern", "Quant Risk Intern"],
    skills: [
      { id: "financial_risk",  weight: 3, impact: "Measuring market/credit risk is the daily work." },
      { id: "risk_management", weight: 3, impact: "You frame and manage the firm's risk exposure." },
      { id: "statistics",      weight: 2, impact: "Risk models are estimated and validated statistically." },
      { id: "time_series",     weight: 2, impact: "Risk evolves over time; you forecast it." },
      { id: "finance",         weight: 2, impact: "You work in the language of markets and instruments." },
      { id: "stochastics",     weight: 1, impact: "Pricing and simulation rest on stochastic models." },
    ],
  },
  {
    id: "actuary",
    title: "Actuary / Insurance Analyst",
    summary: "Price risk and reserve capital for insurance, pensions, and benefits.",
    outlook: "Specialised, credential-driven, and reliably in demand.",
    sampleRoles: ["Actuarial Analyst", "Pricing Actuary", "Pensions Analyst"],
    internships: ["Actuarial Intern", "Insurance Analytics Intern"],
    skills: [
      { id: "actuarial",   weight: 3, impact: "Pricing and reserving methods are the core craft." },
      { id: "stochastics", weight: 3, impact: "Insurance is built on stochastic modelling." },
      { id: "statistics",  weight: 2, impact: "You estimate frequencies and severities from data." },
      { id: "finance",     weight: 2, impact: "Reserves are invested and managed financially." },
      { id: "time_series", weight: 1, impact: "Claims and rates are modelled over time." },
    ],
  },
  {
    id: "product_manager",
    title: "Product Manager",
    summary: "Own a product's direction — balancing customers, business, and engineering.",
    outlook: "Highly sought; the I-engineer mix of tech + business fits well.",
    sampleRoles: ["Product Manager", "Technical Product Manager", "Product Owner"],
    internships: ["Product Management Intern", "APM Intern"],
    skills: [
      { id: "business_dev",  weight: 3, impact: "You decide what to build and why it matters." },
      { id: "marketing",     weight: 2, impact: "You understand customers and positioning." },
      { id: "project_mgmt",  weight: 2, impact: "You coordinate delivery across teams." },
      { id: "programming",   weight: 1, impact: "Technical fluency earns engineering's trust." },
      { id: "communication", weight: 2, impact: "You align everyone around the roadmap." },
    ],
  },
  {
    id: "entrepreneur",
    title: "Entrepreneur / Business Developer",
    summary: "Start or grow ventures — from idea and funding to a working business.",
    outlook: "Open-ended; the program explicitly trains for it.",
    sampleRoles: ["Founder", "Business Developer", "Venture Analyst"],
    internships: ["Startup Intern", "Venture / Incubator Intern"],
    skills: [
      { id: "entrepreneurship", weight: 3, impact: "Building something from nothing is the role." },
      { id: "business_dev",     weight: 3, impact: "You find and grow the opportunity." },
      { id: "finance",          weight: 2, impact: "You raise and manage money to survive." },
      { id: "marketing",        weight: 2, impact: "No customers, no business." },
      { id: "leadership",       weight: 1, impact: "You build and lead the first team." },
    ],
  },
  {
    id: "quality_engineer",
    title: "Quality / Process Engineer (Lean Six Sigma)",
    summary: "Drive quality and continuous improvement across processes and products.",
    outlook: "Essential in manufacturing and increasingly in services.",
    sampleRoles: ["Quality Engineer", "Process Engineer", "CI Specialist"],
    internships: ["Quality Engineering Intern", "Process Improvement Intern"],
    skills: [
      { id: "quality_mgmt", weight: 3, impact: "Lean/Six Sigma methods are the whole job." },
      { id: "statistics",   weight: 2, impact: "SPC and DOE rely on statistics." },
      { id: "production",   weight: 2, impact: "You improve how things are produced." },
      { id: "project_mgmt", weight: 1, impact: "Improvements are run as projects." },
    ],
  },
  {
    id: "sustainability",
    title: "Sustainability / Energy Analyst",
    summary: "Help organisations cut emissions, costs, and risk through better systems.",
    outlook: "Growing fast with the energy transition and reporting rules.",
    sampleRoles: ["Sustainability Analyst", "ESG Analyst", "Energy Analyst"],
    internships: ["Sustainability Intern", "ESG / Energy Intern"],
    skills: [
      { id: "sustainability", weight: 3, impact: "Sustainability is the lens for everything you do." },
      { id: "economics",      weight: 2, impact: "Trade-offs are economic as well as environmental." },
      { id: "statistics",     weight: 2, impact: "You quantify impact and track progress." },
      { id: "optimization",   weight: 1, impact: "Resource and energy use can be optimised." },
      { id: "communication",  weight: 1, impact: "Reporting to stakeholders is a core deliverable." },
    ],
  },
];

const STEM_DATA = {
  program: PROGRAM,
  tracks: TRACKS,
  skills: SKILLS,
  courses: COURSES,
  careers: CAREERS,
  meta: {
    sources: [
      "https://www.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi/",
      "https://www2.umu.se/utbildning/program/civilingenjorsprogrammet-i-industriell-ekonomi",
    ],
    note:
      "Years 1–3 courses follow Umeå's published utbildningsplan. Years 4–5 " +
      "specialization courses are representative placeholders to be replaced with " +
      "the official kursplaner.",
  },
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = STEM_DATA;
} else {
  window.STEM_DATA = STEM_DATA;
}
