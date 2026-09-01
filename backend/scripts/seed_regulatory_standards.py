import asyncio

from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.system import RegulatoryStandard

REGULATORY_STANDARDS = [
    {
        "code": "CBUAE MMG §4.2",
        "title": "Model Management & Validation Standards",
        "authority": "Central Bank of the UAE",
        "jurisdiction": "United Arab Emirates",
        "effective_date": "2023-01-01",
        "category": "Model Risk Management",
        "description": "Requires licensed financial institutions to conduct rigorous annual independent validation, out-of-time degradation monitoring, and explainability audits for all internal credit rating systems.",
        "clauses_json": [
            {
                "clause": "§4.2.1",
                "topic": "Stability Degradation Tolerance",
                "requirement": "Out-of-time discriminatory power degradation exceeding 10% between development and validation cohorts requires immediate mitigation.",
                "threshold": "Max 10% Gini Delta",
            },
            {
                "clause": "§4.2.4",
                "topic": "Variable Selection & Multicollinearity",
                "requirement": "All predictive risk drivers must demonstrate Information Value (IV) > 0.02 and Variance Inflation Factor (VIF) < 2.5.",
                "threshold": "IV ≥ 0.02, VIF < 2.5",
            },
            {
                "clause": "§4.3.2",
                "topic": "Independent Benchmarking",
                "requirement": "Challenger models must be run concurrently with baseline implementations to test architectural sensitivity.",
                "threshold": "Required annually",
            },
        ],
    },
    {
        "code": "IFRS 9 ECL",
        "title": "Financial Instruments: Impairment & Stage Allocation",
        "authority": "International Accounting Standards Board (IASB)",
        "jurisdiction": "Global / Multi-Jurisdictional",
        "effective_date": "2018-01-01",
        "category": "Accounting & Provisioning",
        "description": "Establishes a forward-looking expected credit loss (ECL) model requiring continuous monitoring of Significant Increase in Credit Risk (SICR) across 3 stages.",
        "clauses_json": [
            {
                "clause": "IFRS 9.B5.5.17",
                "topic": "Forward-Looking Macro Scenarios",
                "requirement": "Estimates of expected credit losses must reflect an unbiased and probability-weighted amount across multiple forward-looking economic trajectories.",
                "threshold": "Min 3 Scenarios",
            },
            {
                "clause": "IFRS 9.5.5.3",
                "topic": "SICR Staging Transition",
                "requirement": "Lifetime ECL must be recognized when credit risk on an instrument has increased significantly since initial recognition.",
                "threshold": "Relative PD Doubling / 30 DPD Backstop",
            },
        ],
    },
    {
        "code": "FRB SR 11-7 / OCC 2011-12",
        "title": "Guidance on Model Risk Management",
        "authority": "Federal Reserve Board & OCC",
        "jurisdiction": "United States",
        "effective_date": "2011-04-04",
        "category": "Supervisory Guidance",
        "description": "The global benchmark framework for comprehensive model risk governance, model inventory maintenance, conceptual soundness verification, and ongoing outcomes analysis.",
        "clauses_json": [
            {
                "clause": "Section III",
                "topic": "Conceptual Soundness & Development",
                "requirement": "Rigorous assessment of data quality, theoretical logic, variable choice, and mathematical formulations.",
                "threshold": "Mandatory before deployment",
            },
            {
                "clause": "Section IV",
                "topic": "Ongoing Monitoring & Benchmarking",
                "requirement": "Periodic benchmarking against alternate models and monitoring of population drift (PSI < 0.10).",
                "threshold": "PSI < 0.10 (Green), PSI > 0.25 (Red)",
            },
        ],
    },
    {
        "code": "Basel III/IV IRB",
        "title": "Internal Ratings-Based Approach for Credit Risk",
        "authority": "Basel Committee on Banking Supervision (BCBS)",
        "jurisdiction": "International Banking Framework",
        "effective_date": "2023-01-01",
        "category": "Capital Adequacy & Prudential",
        "description": "Specifies quantitative requirements for estimating PD, LGD, and EAD parameters used in regulatory capital calculations.",
        "clauses_json": [
            {
                "clause": "CRE 32.12",
                "topic": "Historical Data Sample Horizon",
                "requirement": "PD estimation must rely on a minimum of 5 years of historical default observations spanning at least one full economic cycle.",
                "threshold": "Min 5 Years (60 Months)",
            },
            {
                "clause": "CRE 32.44",
                "topic": "Conservative Margin of Margin (MoC)",
                "requirement": "Institutions must add a margin of conservativism to account for statistical sampling error and parameter estimation uncertainty.",
                "threshold": "MoC A/B/C classification",
            },
        ],
    },
]


async def main():
    async with async_session_maker() as session:
        for std in REGULATORY_STANDARDS:
            existing = await session.execute(
                select(RegulatoryStandard).where(RegulatoryStandard.code == std["code"])
            )
            if existing.scalars().first() is not None:
                print(f"Skipping existing standard: {std['code']}")
                continue

            session.add(RegulatoryStandard(**std))
            print(f"Seeded standard: {std['code']}")

        await session.commit()

    print("Regulatory standards seed complete.")


if __name__ == "__main__":
    asyncio.run(main())