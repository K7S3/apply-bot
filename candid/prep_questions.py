"""Researched interview-question banks for the interview-prep feature.

Every question in QUESTIONS_DB was found through public web research
(candidate write-ups, interview guides, question banks). Each entry carries
its source and, where known, when it was reported — so the generated prep
packs never invent "recently asked" questions.

Companies are keyed by a normalized name (lowercase, alphanumeric only);
see interview_prep.normalize_company() for the matching logic.

GENERIC_BANKS are role-family question banks clearly labeled in the pack as
*general preparation* (not verified as asked at that company).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Company-specific banks: real reported questions, with sources.
# Fields: q, category, source, url, reported
# ---------------------------------------------------------------------------

QUESTIONS_DB: dict[str, list[dict]] = {
    "capitalone": [
        {
            "q": "How would you use data to decide whether to approve a credit line increase for certain customers?",
            "category": "case",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026), 'Examples from recent Power Days'",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Design a system to flag unusual transaction patterns in real-time.",
            "category": "case",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026), 'Examples from recent Power Days'",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Analyze a dataset of customer interactions to improve retention.",
            "category": "case",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026), 'Examples from recent Power Days'",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Our credit card application drop-off rate is up 5%. Why?",
            "category": "case",
            "source": "Medium (@nianxiaoming) — 'The Blueprint: Cracking Capital One's Data Science Power Day in 2026' (case analyst round example)",
            "url": "https://medium.com/@nianxiaoming/the-blueprint-cracking-capital-ones-data-science-power-day-in-2026-dad06fc8294f",
            "reported": "2026",
        },
        {
            "q": "Tell me about a time you dealt with conflicting feedback from stakeholders on a model.",
            "category": "behavioral",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026)",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Describe a project where your analysis influenced a business decision. What was the impact?",
            "category": "behavioral",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026)",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "How have you handled a situation where data was incomplete or unreliable?",
            "category": "behavioral",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026)",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Tell me about a time you led a cross-functional team or explained technical results to non-technical leaders.",
            "category": "behavioral",
            "source": "Medium (davidfosterhq) — Capital One Data Scientist Interview Questions & Guide (2026)",
            "url": "https://davidfosterhq.medium.com/capital-one-data-scientist-interview-questions-guide-2026-50153e18d8ca",
            "reported": "2026",
        },
        {
            "q": "Role-play: explain a data science recommendation to a non-technical stakeholder who pushes back. Simplify without losing the technical truth.",
            "category": "case",
            "source": "Medium (@nianxiaoming) — Capital One Power Day 'Role Play' round description (2026)",
            "url": "https://medium.com/@nianxiaoming/the-blueprint-cracking-capital-ones-data-science-power-day-in-2026-dad06fc8294f",
            "reported": "2026",
        },
        {
            "q": "Tell me about an analytical project you've done in the past.",
            "category": "behavioral",
            "source": "Glassdoor — Capital One interview report (New York, NY), interviewed June 2026",
            "url": "https://www.glassdoor.sg/Interview/Capital-One-Interview-Questions-E3736.htm?filter.jobTitleExact=Sr.+Business+Analyst",
            "reported": "June 2026 (analyst loop; adjacent role)",
        },
    ],
    "bloomberg": [
        {
            "q": "Define three guardrail metrics that must remain stable for any new model to be considered a 'go' for production.",
            "category": "product",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~2 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "Given these p-values and funnel drop-offs, what is your interpretation of user behavior? What extra logging do you need, and what's your immediate recommendation?",
            "category": "stats",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~4 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~early-2026",
        },
        {
            "q": "Compare how CNNs, RNNs, and Transformers handle the concept of context and memory within a given input dataset.",
            "category": "ml",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~4 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~early-2026",
        },
        {
            "q": "Evaluate these charts and summarize the business impact. How would you pivot the underlying raw data into cohort views to find the root cause of these dips?",
            "category": "product",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~4 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~early-2026",
        },
        {
            "q": "Why do analytical databases often prefer the simpler join logic of a star schema over the storage efficiency of a snowflake schema?",
            "category": "sql",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~4 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~early-2026",
        },
        {
            "q": "Increase processing efficiency by offloading heavy Pandas transformations to a multi-threaded library like Polars.",
            "category": "python",
            "source": "Prepfully — Bloomberg DS 2026 interview question bank (reported ~4 months ago)",
            "url": "https://prepfully.com/interview-questions/bloomberg/data-scientist",
            "reported": "~early-2026",
        },
        {
            "q": "How do you evaluate the performance of a machine learning model?",
            "category": "ml",
            "source": "Interview Query — Bloomberg L.P. Machine Learning Engineer Interview Guide",
            "url": "https://www.interviewquery.com/interview-guides/bloomberg-lp-machine-learning-engineer",
            "reported": "guide (ongoing)",
        },
        {
            "q": "What are some common techniques for fine-tuning a large language model?",
            "category": "ml",
            "source": "Interview Query — Bloomberg L.P. Research Scientist Interview Guide",
            "url": "https://www.interviewquery.com/interview-guides/bloomberg-lp-research-scientist",
            "reported": "guide (ongoing)",
        },
        {
            "q": "Subscription Overlap: given a subscriptions table (user_id, start_date, end_date), write a query that returns whether each user has a subscription date range overlapping any other completed subscription.",
            "category": "sql",
            "source": "Interview Query — Bloomberg L.P. question list (rated Hard)",
            "url": "https://www.interviewquery.com/interview-guides/bloomberg-lp",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "One-hour HackerRank technical screen: coding basics (strings, arrays, hash maps) plus statistics — sampling, hypothesis testing, error calculations, descriptive statistics — and scenario questions on data quality, trends, and outliers.",
            "category": "process",
            "source": "Interview Query — Bloomberg LP Data Scientist Interview Guide (candidate experience report)",
            "url": "https://www.interviewquery.com/interview-guides/bloomberg-lp-data-scientist",
            "reported": "candidate report (guide updated 2026)",
        },
        {
            "q": "Take-home exercise: analyze social-vulnerability-style demographic data limited to census tracts in one county; deliver methodology, calculations, 2-3 visualizations, and 2-3 policy insights as a short presentation.",
            "category": "process",
            "source": "Interview Query — Bloomberg LP Data Scientist Interview Guide (candidate experience report)",
            "url": "https://www.interviewquery.com/interview-guides/bloomberg-lp-data-scientist",
            "reported": "candidate report (guide updated 2026)",
        },
    ],
    "netflix": [
        {
            "q": "Write the equation for building a classifier using Logistic Regression.",
            "category": "ml",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Given a month's worth of login data (account_id, device_id, payment metadata), how would you detect payment fraud?",
            "category": "case",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "How would you design an experiment for a new content recommendation model we're thinking of rolling out? What metrics would matter?",
            "category": "stats",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Write SQL queries to find a time difference between two events.",
            "category": "sql",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "How would you build and test a metric to compare two users' ranked lists of movie/tv show preferences?",
            "category": "product",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "How would you select a representative sample of search queries from five million?",
            "category": "stats",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Why is Rectified Linear Unit (ReLU) a good activation function?",
            "category": "ml",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "How would you determine if the price of a Netflix subscription is truly the deciding factor for a consumer?",
            "category": "stats",
            "source": "TOPBOTS — Netflix Data Science Interview Questions (republished from Interview Query)",
            "url": "https://www.topbots.com/netflix-data-science-interview-questions/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "You've trained a new recommendation model. How do you make sure it's ready to replace the old one in production?",
            "category": "system_design",
            "source": "Medium (@CodeCoup) — 'How Netflix Tests New ML Models Without Breaking Production' (Oct 2025)",
            "url": "https://medium.com/@CodeCoup/how-netflix-tests-new-ml-models-without-breaking-production-82ea26099573",
            "reported": "Oct 2025",
        },
        {
            "q": "Tell me about a time you independently drove a research project from hypothesis to production impact.",
            "category": "behavioral",
            "source": "Medium (davidfosterhq) — Netflix Research Scientist Interview Guide (Jan 2026)",
            "url": "https://davidfosterhq.medium.com/netflix-research-scientist-interview-guide-get-hired-in-2026-b1dd983f0dee",
            "reported": "Jan 2026",
        },
    ],
    "uber": [
        {
            "q": "Tell me about a time you investigated a failed product launch. What metrics did you look at, and what was your ultimate recommendation?",
            "category": "behavioral",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~2 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "Explain the conditions under which XGBoost's regularization parameters outperform the standard bagging approach of Random Forests.",
            "category": "ml",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~2 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "Walk me through your approach to switchback testing versus cluster randomization when evaluating a new ranking algorithm.",
            "category": "stats",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~2 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "Describe the SQL logic and the business meaning behind rolling retention in the context of monthly subscribers.",
            "category": "sql",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~2-3 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "Given observational data from two disparate product campaigns, how would you mathematically structure a quasi-experiment or A/B test if we observe a 3% baseline increase for one product?",
            "category": "stats",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~3 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "How do you architect a driver tree that connects the performance of the core feed algorithm to overall company revenue?",
            "category": "product",
            "source": "Prepfully — 2026 Uber DS interview question bank (reported ~3 months ago)",
            "url": "https://prepfully.com/interview-questions/uber/data-scientist",
            "reported": "~mid-2026",
        },
        {
            "q": "How would you help the leadership with driving a business goal? Explain with an example from your work.",
            "category": "behavioral",
            "source": "Medium (@ananya.writes1105) — 'Data Scientist Interview: Uber' (analytical round, Apr 2026)",
            "url": "https://medium.com/@ananya.writes1105/data-scientist-interview-uber-3b7d6c9348f5",
            "reported": "Apr 2026",
        },
        {
            "q": "You run an A/B test and a guardrail metric hits its threshold — would you still launch? If not, what would be your course of action?",
            "category": "stats",
            "source": "Medium (@ananya.writes1105) — 'Data Scientist Interview: Uber' (analytical round, Apr 2026)",
            "url": "https://medium.com/@ananya.writes1105/data-scientist-interview-uber-3b7d6c9348f5",
            "reported": "Apr 2026",
        },
        {
            "q": "If you are launching a product in an altogether new marketplace, how would you solve the problem of demand prediction?",
            "category": "case",
            "source": "Medium (@ananya.writes1105) — 'Data Scientist Interview: Uber' (analytical round, Apr 2026)",
            "url": "https://medium.com/@ananya.writes1105/data-scientist-interview-uber-3b7d6c9348f5",
            "reported": "Apr 2026",
        },
        {
            "q": "Revenue went up 8% but profit margin went down 4% quarter-over-quarter — root-cause what could have led to this, and propose initiatives to fix it.",
            "category": "case",
            "source": "Medium (@ananya.writes1105) — 'Data Scientist Interview: Uber' (analytical round, Apr 2026)",
            "url": "https://medium.com/@ananya.writes1105/data-scientist-interview-uber-3b7d6c9348f5",
            "reported": "Apr 2026",
        },
        {
            "q": "Design an experiment (A/B test or observational framework) to gauge whether highly-rated shippers get picked more often.",
            "category": "stats",
            "source": "Medium (@ananya.writes1105) — 'Data Scientist Interview: Uber' (experimentation round, Apr 2026)",
            "url": "https://medium.com/@ananya.writes1105/data-scientist-interview-uber-3b7d6c9348f5",
            "reported": "Apr 2026",
        },
        {
            "q": "Calculate the average time between consecutive rides for each driver (SQL: LAG over timestamps, then average).",
            "category": "sql",
            "source": "Medium (davidfosterhq) — Uber Data Scientist Interview: Real Questions & Tips (2026)",
            "url": "https://davidfosterhq.medium.com/uber-data-scientist-interview-real-questions-tips-to-ace-it-2026-46baa7b0ac08",
            "reported": "2026",
        },
        {
            "q": "Write a query to sessionize rides: group consecutive trips within 30 minutes as one session.",
            "category": "sql",
            "source": "Medium (davidfosterhq) — Uber Data Scientist Interview: Real Questions & Tips (2026)",
            "url": "https://davidfosterhq.medium.com/uber-data-scientist-interview-real-questions-tips-to-ace-it-2026-46baa7b0ac08",
            "reported": "2026",
        },
    ],
    "nvidia": [
        {
            "q": "Walk through your most important research contribution — what was actually novel about it?",
            "category": "behavioral",
            "source": "CleverPrep — NVIDIA Research Scientist Interview Questions & Prep Guide (2026)",
            "url": "https://www.cleverprep.com/companies/nvidia/research-scientist",
            "reported": "2026",
        },
        {
            "q": "How would you scale your approach on NVIDIA GPUs / with distributed training?",
            "category": "system_design",
            "source": "CleverPrep — NVIDIA Research Scientist Interview Questions & Prep Guide (2026)",
            "url": "https://www.cleverprep.com/companies/nvidia/research-scientist",
            "reported": "2026",
        },
        {
            "q": "How would you design experiments for an LLM / multimodal problem?",
            "category": "ml",
            "source": "CleverPrep — NVIDIA Research Scientist Interview Questions & Prep Guide (2026)",
            "url": "https://www.cleverprep.com/companies/nvidia/research-scientist",
            "reported": "2026",
        },
        {
            "q": "How would you optimize a PyTorch model for training or inference?",
            "category": "system_design",
            "source": "CleverPrep — NVIDIA Research Scientist Interview Questions & Prep Guide (2026)",
            "url": "https://www.cleverprep.com/companies/nvidia/research-scientist",
            "reported": "2026",
        },
        {
            "q": "What causes vanishing and exploding gradients, and how do modern architectures mitigate them?",
            "category": "ml",
            "source": "Medium (@santosh.rout.cr7) — 'Ace Your NVIDIA ML Interview: Top 25 Questions' (2026 version)",
            "url": "https://medium.com/@santosh.rout.cr7/ace-your-nvidia-ml-interview-top-25-questions-and-expert-answers-2026-version-1d23c57f52aa",
            "reported": "2026",
        },
        {
            "q": "How does numerical precision (FP16 vs FP32) affect convergence and stability in deep learning?",
            "category": "ml",
            "source": "Medium (@santosh.rout.cr7) — 'Ace Your NVIDIA ML Interview: Top 25 Questions' (2026 version)",
            "url": "https://medium.com/@santosh.rout.cr7/ace-your-nvidia-ml-interview-top-25-questions-and-expert-answers-2026-version-1d23c57f52aa",
            "reported": "2026",
        },
        {
            "q": "Given a time series dataset, how would you detect an anomaly?",
            "category": "ml",
            "source": "TOPBOTS — The NVIDIA Data Science Interview (republished from Interview Query)",
            "url": "https://www.topbots.com/the-nvidia-data-science-interview/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Implement gradient descent in TensorFlow.",
            "category": "python",
            "source": "TOPBOTS — The NVIDIA Data Science Interview (republished from Interview Query)",
            "url": "https://www.topbots.com/the-nvidia-data-science-interview/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Design a recommendation engine end to end, from dataset to deployment in production.",
            "category": "system_design",
            "source": "TOPBOTS — The NVIDIA Data Science Interview (republished from Interview Query)",
            "url": "https://www.topbots.com/the-nvidia-data-science-interview/",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Explain how a decision tree works under the hood.",
            "category": "ml",
            "source": "TOPBOTS — The NVIDIA Data Science Interview (republished from Interview Query)",
            "url": "https://www.topbots.com/the-nvidia-data-science-interview/",
            "reported": "question bank (ongoing)",
        },
    ],
    "bankofamerica": [
        {
            "q": "Explain this project on your resume — what steps did you follow? Why did you choose your specific model? What could you have done better?",
            "category": "behavioral",
            "source": "Wall Street Oasis — Bank of America Quantitative Analyst (Credit Risk) interview report (interviewed 2022, submitted Oct 2024)",
            "url": "https://www.wallstreetoasis.com/company/bank-of-america-private-bank/interview",
            "reported": "2022 cycle",
        },
        {
            "q": "Tell me about a time you found a mistake in your work.",
            "category": "behavioral",
            "source": "Wall Street Oasis — Bank of America interview questions collection",
            "url": "https://www.wallstreetoasis.com/company/bank-of-america-private-bank/interview",
            "reported": "question bank (ongoing)",
        },
        {
            "q": "Why do you want to work at Bank of America? Why should Bank of America hire you?",
            "category": "behavioral",
            "source": "eFinancialCareers — 'Every interview question you're likely to be asked by Bank of America' (asked in the last six months)",
            "url": "https://www.efinancialcareers.com/news/bank-of-america-interview-questions",
            "reported": "~2026",
        },
        {
            "q": "Describe a time you used data analysis to solve a problem.",
            "category": "behavioral",
            "source": "KTPYTE/Byte interview guide — Bank Of America Interview Questions And Answers (technical & role-specific section)",
            "url": "https://sf2.useast.cluster.ktbyte.com/uploaded-files/H3DzVf/8OK145/BankOfAmericaInterviewQuestionsAndAnswers.pdf",
            "reported": "guide (ongoing)",
        },
        {
            "q": "What are the Greeks? What is the relationship between first- and second-order Greeks?",
            "category": "quant",
            "source": "eFinancialCareers — Bank of America Sales & Trading interview questions (asked in the last six months)",
            "url": "https://www.efinancialcareers.com/news/bank-of-america-interview-questions",
            "reported": "~2026 (markets roles; relevant for quant-adjacent loops)",
        },
        {
            "q": "How do you calculate the price of an option? Pitch a stock to me.",
            "category": "quant",
            "source": "eFinancialCareers — Bank of America Sales & Trading interview questions (asked in the last six months)",
            "url": "https://www.efinancialcareers.com/news/bank-of-america-interview-questions",
            "reported": "~2026 (markets roles; relevant for quant-adjacent loops)",
        },
    ],
}


# ---------------------------------------------------------------------------
# Generic role-family banks. Labeled in the pack as general preparation —
# NOT verified as asked at any specific company.
# ---------------------------------------------------------------------------

GENERIC_BANKS: dict[str, list[dict]] = {
    "data_scientist": [
        {"q": "Design an A/B test for a new feature. How do you pick the sample size, and what do you do about peeking?", "category": "stats"},
        {"q": "Your model's offline metrics improved but the online metric didn't move. Walk me through your debugging.", "category": "ml"},
        {"q": "How do you handle imbalanced classes in a classification problem?", "category": "ml"},
        {"q": "Explain bias-variance tradeoff with a concrete example from your work.", "category": "ml"},
        {"q": "Write a SQL query using window functions to compute a 7-day rolling average.", "category": "sql"},
        {"q": "How do you detect and handle data leakage?", "category": "ml"},
        {"q": "Design a metric tree for a subscription product. What is the north-star metric and why?", "category": "product"},
    ],
    "ml_engineer": [
        {"q": "Design an ML system end to end: data, training, serving, monitoring. Where does feature computation live?", "category": "system_design"},
        {"q": "How do you detect that a model in production has gone stale? What do you monitor — inputs or outputs?", "category": "system_design"},
        {"q": "Explain training/serving skew and how you prevent it.", "category": "system_design"},
        {"q": "How would you evaluate an LLM-powered feature? What metrics beyond accuracy matter?", "category": "ml"},
        {"q": "Design a RAG pipeline. How do you chunk, retrieve, and know it's working?", "category": "system_design"},
        {"q": "Your inference costs are dominating the model's value. What levers do you pull, in what order?", "category": "system_design"},
        {"q": "How do you version data, code, and models so an experiment is reproducible?", "category": "system_design"},
    ],
    "data_analyst": [
        {"q": "Revenue dropped 10% week-over-week. How do you find the root cause?", "category": "case"},
        {"q": "Write a query to find the second-highest value per group without window functions, then with them.", "category": "sql"},
        {"q": "How do you explain a confidence interval to a non-technical stakeholder?", "category": "stats"},
        {"q": "Design a dashboard for an executive vs. for an analyst. What's different?", "category": "product"},
    ],
    "quant": [
        {"q": "Explain the difference between risk-neutral and real-world pricing.", "category": "quant"},
        {"q": "How do you backtest a trading signal without overfitting?", "category": "quant"},
        {"q": "What is the Sharpe ratio's biggest blind spot?", "category": "quant"},
    ],
    "behavioral": [
        {"q": "Tell me about a time you disagreed with your manager or a stakeholder. What did you do?", "category": "behavioral"},
        {"q": "Describe your biggest professional failure and what it changed about how you work.", "category": "behavioral"},
        {"q": "Tell me about a time you had to learn something completely new under a deadline.", "category": "behavioral"},
        {"q": "Why this company, and why this role specifically?", "category": "behavioral"},
    ],
}
