"""Role plan shared by every job fetching script: target audience + freshers.

WHO THIS PORTAL SERVES
----------------------
Two audiences, not one:

  TRACK A - the target audience. IT infrastructure and operations people
            with 1 to 5 years of experience earning Rs 4 LPA and above,
            exactly as target_audience_hiring_criteria.txt and
            target_audience_jobs.txt describe them.

  TRACK B - freshers of every kind. Anyone with 0 years of experience, in
            any department, not only IT. A nursing fresher, an accounts
            fresher and a desktop support fresher are all users of this
            portal and all of them need jobs waiting for them when they
            arrive.

Before this version the plan was Track A only (85 IT roles) and
is_non_it_title() rejected every non-IT row on the way to disk, so the
portal could never hold a single non-IT fresher job. This file adds Track B
without taking anything away from Track A.

WHAT THIS FILE PRODUCES
-----------------------
1. build_role_plan() - the crawl plan, roughly 1,250 unique search keywords:

     Track A   200 keywords, split exactly 50 / 30 / 20 as the
               "IMPORTANT NOTE - JOB DATA FETCHING PRIORITY" section of
               target_audience_jobs.txt requires:
                 100 (50%)  the 15 priority job profiles, each expanded
                            into its real-world search synonyms
                  60 (30%)  the remaining target-audience job profiles
                  40 (20%)  other highly demanded Indian IT roles

     Track B   every fresher-plausible job title in
               FRESHER_ROLES_BY_DEPARTMENT below: 116 departments, the
               complete fresher_roles.py corpus, minus the titles that
               cannot possibly be a 0-year job (Senior X, X Lead, X Manager,
               X Architect, Head of X - see DROP_SENIOR_TITLES).

   Why keyword variants instead of repeating a role: Freshersworld and
   Shine validate the plan as a permutation of itself and reject any plan
   containing the same string twice (ShineScraper.py's
   _shine_role_plan_is_valid), so a role cannot be weighted by listing it
   again. Both of those scripts also shuffle the plan once per cycle, which
   means a role's share of crawl effort is simply its share of plan
   membership. Distinct genuine synonyms are therefore the only honest way
   to give the priority profiles their mandated 50% - and they are useful in
   themselves, because "Windows Admin" and "Active Directory Administrator"
   return job rows that a "Windows Administrator" search does not.

2. is_non_it_title() - unchanged name, unchanged contract (True means drop
   the row), new meaning: it now rejects only what serves NEITHER audience.
   It is a two-track whitelist instead of the old IT-only blocklist. See the
   function for the exact order of decisions.

3. role_department() - the department a role belongs to, so a nursing
   fresher row is labelled "Nursing" instead of "IT Department". The three
   scrapers read it through one small wrapper each; see the
   DEPARTMENT_LABEL_FIX_APPLIED block in JobDataScraper.py, ShineScraper.py
   and find_naukri_job.py.

WHAT IT COSTS
-------------
A full cycle visits roughly 14 times as many roles per city as the 85-role
plan did. The number of target-audience searches per cycle is unchanged, but
a cycle takes proportionally longer to come back around. If that becomes a
problem, FRESHER_ROLES_PER_DEPARTMENT below is the one knob that shortens
it, and nothing else has to change.

MAINTENANCE
-----------
Every script folder is self-contained ON PURPOSE: freshersworld_script,
naukri_script and shine_script must never import anything from outside their
own folder. That is why the whole fresher corpus is embedded below instead of
being imported from ../fresher_roles.py, and why this file exists as three
byte-identical copies:

    freshersworld_script/target_audience_roles.py
    naukri_script/target_audience_roles.py
    shine_script/target_audience_roles.py

IF YOU EDIT ONE, COPY IT OVER THE OTHER TWO. `md5sum */target_audience_roles.py`
must print the same hash three times.

This module holds data and pure functions only. It imports nothing but `re`,
so it is safe to import from any scraper. Run it directly to see what it
produces:

    python3 target_audience_roles.py
"""

import re


# ---------------------------------------------------------------------------
# Switches. Each one is a single value and nothing else in the file has to
# change when you move it.
# ---------------------------------------------------------------------------

# Drop titles that can never be a 0-year job (Senior X, X Lead, X Manager,
# X Architect, Head of X) from TRACK B. 249 of the corpus's 1,372 titles are
# like that, and a "Senior Backend Developer" or "Area Sales Manager" search
# cannot return a fresher job, so those searches would be spent crawl budget
# with nothing to show for it. Set to False to crawl the corpus verbatim.
DROP_SENIOR_TITLES = True

# Cap on how many titles each department contributes to TRACK B.
#   None -> every fresher-plausible title (full coverage, longest cycle)
#   8    -> about 560 keywords, roughly half the cycle length
#   4    -> about 330 keywords, roughly a quarter
# Titles are kept in the order they appear in the corpus, which puts each
# department's commonest entry-level roles first.
FRESHER_ROLES_PER_DEPARTMENT = None

# Row-level enforcement of the two audiences' hard criteria (1-5 years and
# Rs 4 LPA for Track A, 0 years for Track B). DORMANT by design: the three
# scrapers currently hand the filter a bare job title, so there is no
# experience or salary value to test. classify_job() below implements it and
# is ready to use; turning it on needs the one-line call-site change
# documented there. Until then the title-level whitelist is what runs.
STRICT_EXPERIENCE_MODE = False

# Track A's hard criteria, from target_audience_hiring_criteria.txt.
TARGET_MIN_EXPERIENCE_YEARS = 1
TARGET_MAX_EXPERIENCE_YEARS = 5
TARGET_MIN_SALARY_LPA = 4.0

# Track B's definition of a fresher.
FRESHER_MAX_EXPERIENCE_YEARS = 0

# The department every IT role and every unrecognised role is labelled with.
# This is what the scrapers used for all 85 roles before Track B existed.
DEFAULT_DEPARTMENT = "IT Department"

# How many priority keywords are pinned to the very front of the plan.
#
# All three scrapers shuffle the plan once per cycle, so this head is not
# what a healthy run crawls first. It decides the CANONICAL order - the one
# every scraper falls back to when a shuffle cannot be validated or
# persisted, and the one a reader sees when running this file directly.
PRIORITY_HEAD_SIZE = 20


# ===========================================================================
# TRACK A - the target audience
# ===========================================================================

# ---------------------------------------------------------------------------
# 50% - the 15 priority job profiles (A to O in target_audience_jobs.txt),
# each expanded into the search keywords Indian job portals actually carry
# for it. 100 keywords.
#
# The profile each keyword belongs to is kept visible deliberately: when a
# profile stops producing jobs, this is where you look to see which phrasings
# were tried for it.
# ---------------------------------------------------------------------------

PRIORITY_PROFILE_KEYWORDS = {
    "A. Infrastructure Support Engineer": [
        "Infrastructure Support Engineer",
        "IT Infrastructure Support Engineer",
        "Infrastructure Support Analyst",
        "Infrastructure Support Specialist",
        "Infrastructure Support Administrator",
        "Infra Support Engineer",
        "Infrastructure Technical Support Engineer",
    ],
    "B. L2 Infrastructure Engineer": [
        "L2 Infrastructure Engineer",
        "L2 Support Engineer",
        "L2 Network Engineer",
        "L2 System Engineer",
        "L2 Desktop Support Engineer",
        "L1 L2 Support Engineer",
        "Level 2 Support Engineer",
    ],
    "C. Windows Administrator": [
        "Windows Administrator",
        "Windows Server Administrator",
        "Windows System Administrator",
        "Windows Admin",
        "Active Directory Administrator",
        "Active Directory Engineer",
        "Windows Support Engineer",
    ],
    "D. System Administrator": [
        "System Administrator",
        "Sysadmin",
        "IT System Administrator",
        "Unix System Administrator",
        "VMware Administrator",
        "Hyper V Administrator",
        "Datacenter Engineer",
    ],
    "E. IT Infrastructure Engineer": [
        "IT Infrastructure Engineer",
        "IT Infrastructure Specialist",
        "IT Infrastructure Analyst",
        "IT Infrastructure Administrator",
        "IT Infrastructure Support Analyst",
        "Datacenter Infrastructure Engineer",
        "IT Infrastructure Consultant",
    ],
    "F. Azure Administrator": [
        "Azure Administrator",
        "Azure Admin",
        "Microsoft Azure Administrator",
        "Azure Cloud Administrator",
        "Azure Infrastructure Administrator",
        "Azure Support Engineer",
        "Azure AD Administrator",
    ],
    "G. Azure Infrastructure Engineer": [
        "Azure Infrastructure Engineer",
        "Azure Cloud Infrastructure Engineer",
        "Azure Platform Engineer",
        "Azure Virtual Desktop Engineer",
        "Azure Migration Engineer",
        "Azure Operations Engineer",
        "Azure Infrastructure Support Engineer",
    ],
    "H. Cloud Administrator": [
        "Cloud Administrator",
        "Cloud Admin",
        "Cloud Platform Administrator",
        "Cloud Systems Administrator",
        "Cloud Operations Administrator",
        "Cloud Services Administrator",
    ],
    "I. Cloud Support Engineer": [
        "Cloud Support Engineer",
        "Cloud Technical Support Engineer",
        "Cloud Support Associate",
        "Cloud Support Analyst",
        "Cloud Support Specialist",
        "AWS Support Engineer",
        "AWS Cloud Support Engineer",
    ],
    "J. Cloud Operations Engineer": [
        "Cloud Operations Engineer",
        "Cloud Ops Engineer",
        "CloudOps Engineer",
        "Cloud Operations Specialist",
        "Cloud Monitoring Engineer",
        "Cloud Infrastructure Operations Engineer",
        "Cloud Reliability Engineer",
    ],
    "K. M365 Administrator": [
        "M365 Administrator",
        "Microsoft 365 Administrator",
        "M365 Engineer",
        "Microsoft 365 Engineer",
        "Exchange Online Administrator",
        "Teams Administrator",
        "SharePoint Administrator",
    ],
    "L. Office 365 Administrator": [
        "Office 365 Administrator",
        "O365 Administrator",
        "O365 Admin",
        "Office 365 Engineer",
        "Office 365 Support Engineer",
        "Exchange Administrator",
    ],
    "M. Intune Engineer": [
        "Intune Engineer",
        "Intune Administrator",
        "Microsoft Intune Engineer",
        "MDM Engineer",
        "SCCM Engineer",
        "SCCM Administrator",
    ],
    "N. Endpoint Engineer": [
        "Endpoint Engineer",
        "Endpoint Administrator",
        "Endpoint Management Engineer",
        "Endpoint Security Engineer",
        "Modern Workplace Engineer",
        "Device Management Engineer",
    ],
    "O. IT Specialist": [
        "IT Specialist",
        "Information Technology Specialist",
        "IT Operations Specialist",
        "IT Systems Specialist",
        "IT Services Specialist",
        "Technical Specialist",
    ],
}

PRIORITY_ROLES = [
    keyword
    for keywords in PRIORITY_PROFILE_KEYWORDS.values()
    for keyword in keywords
]


# ---------------------------------------------------------------------------
# 30% - the rest of the target audience's job profiles, copied verbatim from
# target_audience_jobs.txt. These four lists and TARGET_AUDIENCE_ROLES are
# the original 68 titles and are deliberately left exactly as they were:
# other modules and the test suites read them.
#
# Eight of the 68 are also priority profiles (Infrastructure Support
# Engineer, Windows Server Administrator, System Administrator, IT
# Infrastructure Engineer, Azure Administrator, Cloud Administrator, Cloud
# Support Engineer, Cloud Operations Engineer). They are counted once, on the
# priority side, which is what leaves exactly 60 here.
# ---------------------------------------------------------------------------

# IT Support / Help Desk
TARGET_ROLES_IT_SUPPORT = [
    "Desktop Support Engineer",
    "Desktop Support Technician",
    "IT Support Engineer",
    "IT Support Specialist",
    "IT Support Technician",
    "Technical Support Engineer",
    "Technical Support Specialist",
    "Help Desk Technician",
    "Help Desk Engineer",
    "Service Desk Engineer",
    "Service Desk Analyst",
    "IT Service Desk Analyst",
    "IT Support Analyst",
    "End User Support Engineer",
    "End User Computing Engineer",
    "IT Operations Support Engineer",
    "Field Support Engineer",
    "Onsite Support Engineer",
    "IT Technician",
    "IT Administrator",
]

# Network / Infrastructure
TARGET_ROLES_NETWORK = [
    "Network Engineer",
    "Network Support Engineer",
    "Network Administrator",
    "Network Technician",
    "Network Operations Engineer",
    "NOC Engineer",
    "NOC Analyst",
    "Network Operations Analyst",
    "Infrastructure Engineer",
    "Infrastructure Support Engineer",
    "Infrastructure Administrator",
    "IT Infrastructure Engineer",
    "Network Security Engineer",
    "Wireless Network Engineer",
    "LAN WAN Engineer",
    "Network Operations Center Engineer",
    "Network Implementation Engineer",
    "Network Field Engineer",
]

# System / Server
TARGET_ROLES_SYSTEM = [
    "System Engineer",
    "Systems Engineer",
    "Systems Administrator",
    "System Administrator",
    "Server Administrator",
    "Windows Server Administrator",
    "Linux System Administrator",
    "Linux Engineer",
    "Windows System Engineer",
    "Server Support Engineer",
    "Systems Support Engineer",
    "Infrastructure Systems Engineer",
    "IT Systems Engineer",
    "System Operations Engineer",
    "Platform Engineer",
    "Infrastructure Operations Engineer",
]

# Cloud / DevOps Infrastructure (2nd level, from the Azure admin course)
TARGET_ROLES_CLOUD = [
    "Cloud Engineer",
    "Cloud Support Engineer",
    "Cloud Infrastructure Engineer",
    "Cloud Operations Engineer",
    "Cloud Administrator",
    "Azure Administrator",
    "Azure Cloud Engineer",
    "AWS Cloud Engineer",
    "AWS Systems Administrator",
    "DevOps Engineer",
    "DevOps Infrastructure Engineer",
    "Site Reliability Engineer",
    "Cloud Operations Analyst",
    "Cloud Infrastructure Administrator",
]

# The original 68. Unchanged on purpose - this is the list that
# target_audience_jobs.txt calls "All Job Profiles of our Target Audience".
TARGET_AUDIENCE_ROLES = (
    TARGET_ROLES_IT_SUPPORT
    + TARGET_ROLES_NETWORK
    + TARGET_ROLES_SYSTEM
    + TARGET_ROLES_CLOUD
)


# ---------------------------------------------------------------------------
# 20% - other highest-demand IT roles in the Indian market.
#
# HIGH_DEMAND_IT_ROLES is the original 17 and is left untouched for the same
# reason as TARGET_AUDIENCE_ROLES. HIGH_DEMAND_IT_ROLES_EXTRA carries the 23
# added to reach the mandated 20% share of Track A, and TRENDING_IT_ROLES is
# the 40 the plan actually uses.
# ---------------------------------------------------------------------------

HIGH_DEMAND_IT_ROLES = [
    "Java Developer",
    "Python Developer",
    "Full Stack Developer",
    "React Developer",
    "Angular Developer",
    "Node.js Developer",
    ".NET Developer",
    "Automation Test Engineer",
    "QA Engineer",
    "Data Engineer",
    "Data Analyst",
    "Machine Learning Engineer",
    "Cybersecurity Analyst",
    "Salesforce Developer",
    "SAP Consultant",
    "ServiceNow Developer",
    "Database Administrator",
]

HIGH_DEMAND_IT_ROLES_EXTRA = [
    "Software Engineer",
    "Software Developer",
    "Backend Developer",
    "Frontend Developer",
    "Android Developer",
    "iOS Developer",
    "Flutter Developer",
    "PHP Developer",
    "Golang Developer",
    "Business Analyst",
    "Power BI Developer",
    "Data Scientist",
    "AI Engineer",
    "Scrum Master",
    "UI UX Designer",
    "Embedded Software Engineer",
    "Oracle DBA",
    "SQL Developer",
    "Kubernetes Engineer",
    "Big Data Engineer",
    "Mainframe Developer",
    "SharePoint Developer",
    "Performance Test Engineer",
]

TRENDING_IT_ROLES = HIGH_DEMAND_IT_ROLES + HIGH_DEMAND_IT_ROLES_EXTRA


# ===========================================================================
# TRACK B - freshers of every kind
# ===========================================================================
# The complete fresher_roles.py corpus: 116 departments, 1464 job titles, IT
# first and then every other department the portal serves.
#
# EMBEDDED, NOT IMPORTED. freshersworld_script, naukri_script and
# shine_script must each be able to run from a copy of their own folder
# alone, so none of them may import ../fresher_roles.py. Keeping the corpus
# here is what makes that true. When fresher_roles.py changes, regenerate
# this section in all three copies.
#
# Senior titles are still listed below exactly as the corpus has them. They
# are filtered out when the plan is built, not here, so that
# DROP_SENIOR_TITLES stays a one-value decision and nothing is lost from the
# record of what the corpus contains.
# ===========================================================================

FRESHER_ROLES_BY_DEPARTMENT = {
    "IT Department": [
        "IT Manager",
        "IT Executive",
        "IT Officer",
        "IT Coordinator",
        "IT Administrator",
        "IT Analyst",
        "IT Consultant",
        "IT Specialist",
        "IT Engineer",
        "IT Technician",
        "IT Operations Manager",
        "IT Service Manager",
        "IT Asset Manager",
        "IT Helpdesk Executive",
        "IT Support Engineer",
        "Software Developer",
        "Software Engineer",
        "Junior Software Developer",
        "Senior Software Developer",
        "Software Programmer",
        "Application Developer",
        "Application Engineer",
        "Java Developer",
        "Python Developer",
        "PHP Developer",
        "Node.js Developer",
        ".NET Developer",
        "C++ Developer",
        "C# Developer",
        "Go Developer",
        "Ruby Developer",
        "Software Architect",
        "Technical Lead",
        "Engineering Manager",
        "Web Developer",
        "Junior Web Developer",
        "Senior Web Developer",
        "Website Developer",
        "PHP Web Developer",
        "WordPress Developer",
        "Shopify Developer",
        "Laravel Developer",
        "Django Developer",
        "Flask Developer",
        "MERN Stack Developer",
        "Web Application Developer",
        "Web Designer",
        "Webmaster",
        "Mobile App Developer",
        "Android Developer",
        "iOS Developer",
        "Flutter Developer",
        "React Native Developer",
        "Kotlin Developer",
        "Swift Developer",
        "Mobile Application Engineer",
        "Hybrid App Developer",
        "Mobile UI Developer",
        "Mobile App Tester",
        "Senior Mobile Developer",
        "Frontend Developer",
        "Frontend Engineer",
        "React Developer",
        "Angular Developer",
        "Vue.js Developer",
        "JavaScript Developer",
        "TypeScript Developer",
        "HTML CSS Developer",
        "UI Developer",
        "Web UI Developer",
        "Frontend Lead",
        "Senior Frontend Developer",
        "Backend Developer",
        "Backend Engineer",
        "API Developer",
        "Server Side Developer",
        "Java Backend Developer",
        "Python Backend Developer",
        "Node.js Backend Developer",
        "PHP Backend Developer",
        "Django Backend Developer",
        "Spring Boot Developer",
        "Database Backend Developer",
        "Backend Lead",
        "Senior Backend Developer",
        "Full Stack Developer",
        "Full Stack Engineer",
        "MEAN Stack Developer",
        "Java Full Stack Developer",
        "Python Full Stack Developer",
        "PHP Full Stack Developer",
        ".NET Full Stack Developer",
        "React Full Stack Developer",
        "Angular Full Stack Developer",
        "Senior Full Stack Developer",
        "Full Stack Technical Lead",
        "DevOps Engineer",
        "DevOps Developer",
        "DevOps Architect",
        "Cloud DevOps Engineer",
        "AWS DevOps Engineer",
        "Azure DevOps Engineer",
        "CI CD Engineer",
        "Build and Release Engineer",
        "Site Reliability Engineer",
        "Infrastructure Engineer",
        "Platform Engineer",
        "Docker Engineer",
        "Kubernetes Engineer",
        "Cloud Engineer",
        "Cloud Architect",
        "Cloud Administrator",
        "Cloud Consultant",
        "AWS Engineer",
        "Azure Engineer",
        "Google Cloud Engineer",
        "Cloud Support Engineer",
        "Cloud Security Engineer",
        "Cloud Infrastructure Engineer",
        "Cloud Operations Engineer",
        "Cloud Migration Engineer",
        "Cloud Solution Architect",
        "Cyber Security Analyst",
        "Cyber Security Engineer",
        "Security Analyst",
        "Information Security Analyst",
        "SOC Analyst",
        "Security Engineer",
        "Ethical Hacker",
        "Penetration Tester",
        "Vulnerability Analyst",
        "Network Security Engineer",
        "Application Security Engineer",
        "Security Consultant",
        "Cyber Security Manager",
        "Network Administrator",
        "Network Engineer",
        "Network Support Engineer",
        "Network Technician",
        "Network Analyst",
        "LAN WAN Engineer",
        "Routing and Switching Engineer",
        "Firewall Engineer",
        "NOC Engineer",
        "Wireless Network Engineer",
        "Senior Network Administrator",
        "System Administrator",
        "Linux Administrator",
        "Windows Administrator",
        "Server Administrator",
        "System Engineer",
        "System Support Engineer",
        "Infrastructure Administrator",
        "VMware Administrator",
        "Active Directory Administrator",
        "Backup Administrator",
        "System Operations Engineer",
        "Database Administrator",
        "SQL DBA",
        "MySQL DBA",
        "PostgreSQL DBA",
        "Oracle DBA",
        "MongoDB Administrator",
        "Database Engineer",
        "Database Developer",
        "Data Warehouse Administrator",
        "Database Analyst",
        "Senior Database Administrator",
        "Data Scientist",
        "Junior Data Scientist",
        "Senior Data Scientist",
        "Data Science Engineer",
        "Applied Data Scientist",
        "Research Data Scientist",
        "NLP Data Scientist",
        "Computer Vision Scientist",
        "Statistical Analyst",
        "Predictive Modeling Analyst",
        "Data Science Manager",
        "Data Analyst",
        "Junior Data Analyst",
        "Senior Data Analyst",
        "Business Data Analyst",
        "Reporting Analyst",
        "MIS Analyst",
        "Excel Analyst",
        "SQL Analyst",
        "Data Visualization Analyst",
        "Operations Analyst",
        "Marketing Data Analyst",
        "Financial Data Analyst",
        "Business Intelligence Analyst",
        "BI Developer",
        "BI Engineer",
        "Power BI Developer",
        "Tableau Developer",
        "Looker Developer",
        "Data Visualization Developer",
        "BI Consultant",
        "BI Manager",
        "Reporting Developer",
        "Dashboard Developer",
        "AI Engineer",
        "AI Developer",
        "AI Researcher",
        "AI Scientist",
        "Generative AI Engineer",
        "NLP Engineer",
        "Computer Vision Engineer",
        "AI Consultant",
        "AI Product Manager",
        "AI Solution Architect",
        "Prompt Engineer",
        "AI Trainer",
        "Machine Learning Engineer",
        "ML Engineer",
        "Machine Learning Developer",
        "ML Scientist",
        "Deep Learning Engineer",
        "MLOps Engineer",
        "ML Research Engineer",
        "Recommendation System Engineer",
        "Senior Machine Learning Engineer",
        "Quality Assurance Engineer",
        "QA Engineer",
        "QA Analyst",
        "QA Tester",
        "QA Lead",
        "QA Manager",
        "Quality Analyst",
        "Software Quality Analyst",
        "Test Engineer",
        "Test Lead",
        "Quality Assurance Specialist",
        "Software Tester",
        "Testing Engineer",
        "Manual Tester",
        "Automation Tester",
        "Functional Tester",
        "Regression Tester",
        "Performance Tester",
        "Security Tester",
        "Web Application Tester",
        "Test Analyst",
        "Automation Test Engineer",
        "Selenium Tester",
        "Cypress Tester",
        "Playwright Tester",
        "API Automation Tester",
        "Performance Automation Tester",
        "Test Automation Architect",
        "QA Automation Engineer",
        "Automation QA Lead",
        "Manual Test Engineer",
        "QA Manual Tester",
        "UAT Tester",
        "Mobile Manual Tester",
        "Web Manual Tester",
        "Test Case Writer",
        "Bug Tester",
        "IT Support Executive",
        "Desktop Support Engineer",
        "Helpdesk Support Executive",
        "Technical Support Engineer",
        "Hardware Support Engineer",
        "Software Support Engineer",
        "Remote Support Engineer",
        "L1 Support Engineer",
        "L2 Support Engineer",
        "Technical Support Executive",
        "Customer Technical Support",
        "Product Support Engineer",
        "Application Support Engineer",
        "Voice Technical Support",
        "Chat Technical Support",
        "L1 Technical Support",
        "L2 Technical Support",
        "Product Manager",
        "Associate Product Manager",
        "Senior Product Manager",
        "Product Owner",
        "Technical Product Manager",
        "Software Product Manager",
        "Product Analyst",
        "Product Consultant",
        "Product Lead",
        "Product Head",
        "Chief Product Officer",
        "Project Manager",
        "IT Project Manager",
        "Software Project Manager",
        "Technical Project Manager",
        "Project Coordinator",
        "Project Lead",
        "Scrum Master",
        "Agile Project Manager",
        "Delivery Manager",
        "Implementation Manager",
        "Project Director",
        "Program Manager",
        "Technical Program Manager",
        "Senior Program Manager",
        "Program Coordinator",
        "Program Lead",
        "Delivery Program Manager",
        "IT Program Manager",
        "Business Program Manager",
        "Program Director",
        "PMO Manager",
        "UI Designer",
        "UX Designer",
        "UI UX Designer",
        "Product Designer",
        "Interaction Designer",
        "Visual Designer",
        "User Researcher",
        "UX Researcher",
        "Wireframe Designer",
        "Prototype Designer",
        "Figma Designer",
        "Design Lead",
        "Game Developer",
        "Unity Developer",
        "Unreal Engine Developer",
        "Game Programmer",
        "Gameplay Programmer",
        "Game Designer",
        "Level Designer",
        "Game Artist",
        "3D Game Artist",
        "Game Tester",
        "Mobile Game Developer",
        "Blockchain Developer",
        "Blockchain Engineer",
        "Smart Contract Developer",
        "Solidity Developer",
        "Web3 Developer",
        "Crypto Developer",
        "Blockchain Architect",
        "DApp Developer",
        "NFT Developer",
        "Blockchain Consultant",
        "ERP Consultant",
        "ERP Developer",
        "ERP Administrator",
        "ERP Functional Consultant",
        "ERP Technical Consultant",
        "ERP Implementation Consultant",
        "ERP Support Executive",
        "ERP Analyst",
        "ERP Project Manager",
        "Odoo Developer",
        "Oracle ERP Consultant",
        "CRM Executive",
        "CRM Manager",
        "CRM Developer",
        "CRM Administrator",
        "CRM Analyst",
        "CRM Consultant",
        "Salesforce Developer",
        "Salesforce Administrator",
        "Zoho CRM Developer",
        "CRM Support Executive",
        "CRM Implementation Consultant",
        "SAP Consultant",
        "SAP Developer",
        "SAP ABAP Developer",
        "SAP Functional Consultant",
        "SAP Basis Administrator",
        "SAP FICO Consultant",
        "SAP MM Consultant",
        "SAP SD Consultant",
        "SAP HCM Consultant",
        "SAP Project Manager",
        "SAP Support Consultant",
        "IT Infrastructure Engineer",
        "Infrastructure Manager",
        "Infrastructure Architect",
        "Server Engineer",
        "Data Center Engineer",
        "Network Infrastructure Engineer",
        "Infrastructure Support Engineer",
        "IT Asset Executive",
        "IT Operations Executive",
        "IT Operations Engineer",
        "Service Desk Engineer",
        "Application Operations Engineer",
        "Production Support Engineer",
        "IT Service Delivery Manager",
        "IT Security Analyst",
        "IT Security Engineer",
        "Information Security Officer",
        "Security Administrator",
        "Security Operations Analyst",
        "Risk and Security Analyst",
        "Identity Access Management Analyst",
        "IT Security Manager",
        "Technical Writer",
        "Documentation Specialist",
        "API Documentation Writer",
        "Software Documentation Writer",
        "Content Documentation Executive",
        "User Manual Writer",
        "Technical Content Writer",
        "Knowledge Base Writer",
        "Instructional Writer",
        "Documentation Manager",
    ],
    "Administration": [
        "Admin Executive",
        "Admin Manager",
        "Office Administrator",
        "Office Assistant",
        "Administrative Assistant",
        "Front Office Executive",
        "Receptionist",
        "Office Coordinator",
        "Executive Assistant",
        "Personal Assistant",
        "Facility Administrator",
    ],
    "Accounts": [
        "Accountant",
        "Junior Accountant",
        "Senior Accountant",
        "Accounts Executive",
        "Accounts Assistant",
        "Accounts Manager",
        "Accounts Officer",
        "Billing Executive",
        "Bookkeeper",
        "Tally Operator",
        "Ledger Executive",
    ],
    "Finance": [
        "Finance Executive",
        "Finance Analyst",
        "Finance Manager",
        "Financial Analyst",
        "Financial Controller",
        "Budget Analyst",
        "Treasury Executive",
        "Investment Analyst",
        "Credit Analyst",
        "Finance Officer",
        "Chief Financial Officer",
    ],
    "Audit": [
        "Audit Executive",
        "Audit Assistant",
        "Internal Auditor",
        "External Auditor",
        "Senior Auditor",
        "Audit Manager",
        "Financial Auditor",
        "Compliance Auditor",
        "Stock Auditor",
        "Process Auditor",
        "Risk Auditor",
    ],
    "Taxation": [
        "Tax Executive",
        "Tax Consultant",
        "GST Executive",
        "Income Tax Executive",
        "Tax Analyst",
        "Tax Manager",
        "Direct Tax Consultant",
        "Indirect Tax Consultant",
        "Taxation Officer",
        "GST Accountant",
    ],
    "Human Resources": [
        "HR Executive",
        "HR Manager",
        "HR Generalist",
        "HR Assistant",
        "HR Officer",
        "HR Business Partner",
        "Employee Relations Executive",
        "HR Coordinator",
        "HR Operations Executive",
        "HR Head",
        "Chief Human Resources Officer",
    ],
    "Recruitment": [
        "Recruiter",
        "HR Recruiter",
        "IT Recruiter",
        "Non IT Recruiter",
        "Talent Acquisition Executive",
        "Talent Acquisition Specialist",
        "Recruitment Consultant",
        "Staffing Specialist",
        "Sourcing Specialist",
        "Recruitment Manager",
        "Campus Recruiter",
    ],
    "Training and Development": [
        "Training Executive",
        "Training Manager",
        "Corporate Trainer",
        "Learning and Development Executive",
        "L&D Manager",
        "Soft Skills Trainer",
        "Technical Trainer",
        "Process Trainer",
        "Product Trainer",
        "Instructional Designer",
    ],
    "Payroll": [
        "Payroll Executive",
        "Payroll Specialist",
        "Payroll Officer",
        "Payroll Manager",
        "Salary Processing Executive",
        "Compensation Executive",
        "Benefits Executive",
        "HR Payroll Executive",
        "Payroll Analyst",
    ],
    "Legal": [
        "Legal Executive",
        "Legal Officer",
        "Legal Advisor",
        "Legal Consultant",
        "Corporate Lawyer",
        "Company Secretary",
        "Contract Manager",
        "Legal Manager",
        "Compliance Lawyer",
        "Legal Associate",
    ],
    "Compliance": [
        "Compliance Executive",
        "Compliance Officer",
        "Compliance Analyst",
        "Compliance Manager",
        "Risk Compliance Officer",
        "Regulatory Compliance Executive",
        "Audit Compliance Executive",
        "KYC Compliance Officer",
        "Legal Compliance Manager",
    ],
    "Operations": [
        "Operations Executive",
        "Operations Manager",
        "Operations Coordinator",
        "Operations Analyst",
        "Operations Supervisor",
        "Process Executive",
        "Process Manager",
        "Branch Operations Manager",
        "General Manager Operations",
        "Chief Operating Officer",
    ],
    "Business Operations": [
        "Business Operations Executive",
        "Business Operations Manager",
        "Business Analyst",
        "Operations Analyst",
        "Business Process Analyst",
        "Business Coordinator",
        "Strategy Operations Manager",
        "Business Support Executive",
        "Business Operations Lead",
    ],
    "Sales": [
        "Sales Executive",
        "Sales Officer",
        "Sales Manager",
        "Sales Representative",
        "Sales Associate",
        "Sales Consultant",
        "Area Sales Manager",
        "Regional Sales Manager",
        "Sales Head",
        "Account Executive",
        "Key Account Manager",
    ],
    "Inside Sales": [
        "Inside Sales Executive",
        "Inside Sales Representative",
        "Inside Sales Manager",
        "Sales Development Representative",
        "Lead Generation Executive",
        "Telesales Executive",
        "B2B Sales Executive",
        "Pre Sales Executive",
        "Inside Sales Consultant",
    ],
    "Field Sales": [
        "Field Sales Executive",
        "Field Sales Officer",
        "Field Sales Manager",
        "Territory Sales Executive",
        "Area Sales Executive",
        "Business Sales Executive",
        "Sales Promoter",
        "Medical Representative",
        "Channel Sales Executive",
        "Door to Door Sales Executive",
    ],
    "Business Development": [
        "Business Development Executive",
        "Business Development Manager",
        "BD Executive",
        "BD Manager",
        "Partnership Manager",
        "Growth Manager",
        "Client Acquisition Executive",
        "Market Development Executive",
        "Business Development Associate",
        "Strategic Partnership Manager",
    ],
    "Marketing": [
        "Marketing Executive",
        "Marketing Manager",
        "Marketing Coordinator",
        "Marketing Officer",
        "Marketing Analyst",
        "Marketing Specialist",
        "Product Marketing Manager",
        "Growth Marketing Manager",
        "Campaign Manager",
        "Marketing Head",
    ],
    "Digital Marketing": [
        "Digital Marketing Executive",
        "Digital Marketing Manager",
        "SEO Executive",
        "SEO Specialist",
        "SEM Executive",
        "PPC Specialist",
        "Social Media Executive",
        "Google Ads Specialist",
        "Email Marketing Executive",
        "Performance Marketing Manager",
    ],
    "Content Marketing": [
        "Content Marketing Executive",
        "Content Marketing Manager",
        "Content Strategist",
        "Content Creator",
        "SEO Content Writer",
        "Blog Writer",
        "Social Media Content Executive",
        "Content Editor",
        "Brand Content Manager",
    ],
    "Brand Management": [
        "Brand Executive",
        "Brand Manager",
        "Assistant Brand Manager",
        "Brand Strategist",
        "Brand Marketing Manager",
        "Brand Communication Manager",
        "Brand Analyst",
        "Creative Brand Manager",
    ],
    "Public Relations": [
        "Public Relations Executive",
        "PR Executive",
        "PR Manager",
        "Media Relations Executive",
        "Corporate Communication Executive",
        "Communication Manager",
        "Press Officer",
        "Public Affairs Manager",
        "PR Consultant",
    ],
    "Customer Support": [
        "Customer Support Executive",
        "Customer Support Associate",
        "Customer Support Representative",
        "Customer Care Executive",
        "Customer Success Executive",
        "Support Specialist",
        "Chat Support Executive",
        "Email Support Executive",
        "Voice Support Executive",
        "Customer Support Manager",
    ],
    "Customer Service": [
        "Customer Service Executive",
        "Customer Service Associate",
        "Customer Service Representative",
        "Customer Service Manager",
        "Service Coordinator",
        "Client Service Executive",
        "Customer Care Officer",
        "Service Desk Executive",
        "Customer Experience Executive",
    ],
    "Client Relationship Management": [
        "Client Relationship Executive",
        "Client Relationship Manager",
        "Relationship Manager",
        "Client Success Manager",
        "Customer Relationship Manager",
        "Account Manager",
        "Key Account Manager",
        "Client Servicing Executive",
        "Client Coordinator",
    ],
    "Design": [
        "Designer",
        "Creative Designer",
        "Visual Designer",
        "Product Designer",
        "Design Executive",
        "Design Manager",
        "Design Lead",
        "Layout Designer",
        "Digital Designer",
        "Junior Designer",
    ],
    "Graphic Design": [
        "Graphic Designer",
        "Senior Graphic Designer",
        "Junior Graphic Designer",
        "Creative Graphic Designer",
        "Logo Designer",
        "Brand Designer",
        "Photoshop Designer",
        "Illustrator Designer",
        "Social Media Designer",
        "Print Designer",
    ],
    "Creative Design": [
        "Creative Designer",
        "Creative Head",
        "Creative Director",
        "Art Director",
        "Visual Designer",
        "Campaign Designer",
        "Advertising Designer",
        "Brand Creative Designer",
        "Creative Associate",
    ],
    "Animation": [
        "Animator",
        "2D Animator",
        "3D Animator",
        "Motion Graphics Designer",
        "Character Animator",
        "VFX Artist",
        "Animation Designer",
        "Storyboard Artist",
        "Maya Artist",
        "Blender Artist",
    ],
    "Video Editing": [
        "Video Editor",
        "Senior Video Editor",
        "Junior Video Editor",
        "Film Editor",
        "YouTube Video Editor",
        "Reel Editor",
        "Motion Video Editor",
        "Post Production Editor",
        "Video Production Executive",
    ],
    "Content Writing": [
        "Content Writer",
        "SEO Content Writer",
        "Blog Writer",
        "Article Writer",
        "Website Content Writer",
        "Creative Writer",
        "Content Editor",
        "Content Executive",
        "Content Manager",
        "Academic Content Writer",
    ],
    "Copywriting": [
        "Copywriter",
        "Creative Copywriter",
        "Marketing Copywriter",
        "Advertising Copywriter",
        "SEO Copywriter",
        "Brand Copywriter",
        "Social Media Copywriter",
        "Email Copywriter",
        "Senior Copywriter",
    ],
    "Research and Development": [
        "R&D Engineer",
        "R&D Executive",
        "Research Associate",
        "Research Analyst",
        "Research Scientist",
        "Product Researcher",
        "Development Engineer",
        "Innovation Manager",
        "R&D Manager",
        "Research Officer",
    ],
    "Engineering": [
        "Engineer",
        "Junior Engineer",
        "Senior Engineer",
        "Engineering Manager",
        "Engineering Supervisor",
        "Project Engineer",
        "Design Engineer",
        "Maintenance Engineer",
        "Service Engineer",
        "Site Engineer",
    ],
    "Mechanical Engineering": [
        "Mechanical Engineer",
        "Design Engineer Mechanical",
        "Production Engineer",
        "Maintenance Engineer",
        "HVAC Engineer",
        "Automobile Engineer",
        "Mechanical Design Engineer",
        "Plant Engineer",
        "Quality Engineer Mechanical",
    ],
    "Electrical Engineering": [
        "Electrical Engineer",
        "Electrical Design Engineer",
        "Electrical Maintenance Engineer",
        "Power Engineer",
        "Electrical Site Engineer",
        "Control Panel Engineer",
        "Electrical Supervisor",
        "Testing and Commissioning Engineer",
        "Electrical Project Engineer",
    ],
    "Electronics Engineering": [
        "Electronics Engineer",
        "Embedded Engineer",
        "PCB Design Engineer",
        "Electronics Design Engineer",
        "VLSI Engineer",
        "IoT Engineer",
        "Hardware Engineer",
        "Electronics Technician",
        "Testing Engineer Electronics",
    ],
    "Civil Engineering": [
        "Civil Engineer",
        "Site Engineer",
        "Structural Engineer",
        "Construction Engineer",
        "Planning Engineer",
        "Quantity Surveyor",
        "Civil Supervisor",
        "Highway Engineer",
        "Project Civil Engineer",
    ],
    "Production": [
        "Production Executive",
        "Production Engineer",
        "Production Manager",
        "Production Supervisor",
        "Line Supervisor",
        "Manufacturing Executive",
        "Process Engineer",
        "Production Planner",
        "Plant Production Manager",
    ],
    "Manufacturing": [
        "Manufacturing Engineer",
        "Manufacturing Manager",
        "Manufacturing Supervisor",
        "Plant Manager",
        "Machine Operator",
        "CNC Operator",
        "Assembly Operator",
        "Manufacturing Technician",
        "Industrial Engineer",
    ],
    "Maintenance": [
        "Maintenance Engineer",
        "Maintenance Technician",
        "Maintenance Manager",
        "Electrical Maintenance Engineer",
        "Mechanical Maintenance Engineer",
        "Plant Maintenance Engineer",
        "Service Technician",
        "Facility Maintenance Executive",
    ],
    "Plant Operations": [
        "Plant Operator",
        "Plant Manager",
        "Plant Supervisor",
        "Plant Engineer",
        "Plant Head",
        "Plant Maintenance Engineer",
        "Factory Manager",
        "Shift Incharge",
        "Production Plant Manager",
    ],
    "Quality Control": [
        "Quality Control Executive",
        "QC Inspector",
        "QC Engineer",
        "QC Analyst",
        "QC Manager",
        "Quality Inspector",
        "Lab QC Analyst",
        "Incoming Quality Inspector",
        "Final Quality Inspector",
    ],
    "Quality Management": [
        "Quality Manager",
        "Quality Executive",
        "Quality Engineer",
        "Quality Assurance Manager",
        "Quality Control Manager",
        "ISO Coordinator",
        "QMS Executive",
        "Quality Auditor",
        "Process Quality Manager",
    ],
    "Supply Chain": [
        "Supply Chain Executive",
        "Supply Chain Manager",
        "Supply Chain Analyst",
        "Supply Planner",
        "Demand Planner",
        "Logistics Coordinator",
        "Procurement Analyst",
        "Supply Chain Coordinator",
        "Inventory Planner",
    ],
    "Procurement": [
        "Procurement Executive",
        "Procurement Manager",
        "Procurement Officer",
        "Sourcing Executive",
        "Purchase Executive",
        "Vendor Development Executive",
        "Procurement Analyst",
        "Procurement Specialist",
    ],
    "Purchase": [
        "Purchase Executive",
        "Purchase Manager",
        "Purchase Officer",
        "Purchase Assistant",
        "Buying Executive",
        "Procurement Executive",
        "Vendor Coordinator",
        "Material Purchase Executive",
        "Purchase Analyst",
    ],
    "Vendor Management": [
        "Vendor Manager",
        "Vendor Management Executive",
        "Vendor Coordinator",
        "Vendor Development Executive",
        "Supplier Relationship Manager",
        "Procurement Vendor Manager",
        "Vendor Compliance Executive",
        "Vendor Onboarding Executive",
    ],
    "Inventory Management": [
        "Inventory Executive",
        "Inventory Manager",
        "Inventory Controller",
        "Inventory Analyst",
        "Stock Manager",
        "Stock Controller",
        "Store Keeper",
        "Warehouse Inventory Executive",
        "Material Controller",
    ],
    "Warehouse": [
        "Warehouse Executive",
        "Warehouse Manager",
        "Warehouse Supervisor",
        "Warehouse Associate",
        "Store Keeper",
        "Picker and Packer",
        "Dispatch Executive",
        "Warehouse Coordinator",
        "Warehouse Operations Manager",
    ],
    "Logistics": [
        "Logistics Executive",
        "Logistics Manager",
        "Logistics Coordinator",
        "Transport Coordinator",
        "Dispatch Executive",
        "Fleet Manager",
        "Shipping Executive",
        "Delivery Manager",
        "Logistics Supervisor",
    ],
    "Transportation": [
        "Transport Executive",
        "Transport Manager",
        "Fleet Manager",
        "Driver",
        "Delivery Driver",
        "Transport Coordinator",
        "Route Planner",
        "Vehicle Supervisor",
        "Transport Operations Manager",
    ],
    "Import Export": [
        "Import Export Executive",
        "Export Executive",
        "Import Executive",
        "Export Documentation Executive",
        "Customs Clearance Executive",
        "International Trade Executive",
        "Shipping Documentation Executive",
        "EXIM Manager",
        "Export Sales Executive",
    ],
    "Retail": [
        "Retail Sales Executive",
        "Retail Store Manager",
        "Retail Associate",
        "Store Executive",
        "Store Manager",
        "Cashier",
        "Retail Supervisor",
        "Retail Operations Manager",
        "Customer Sales Associate",
    ],
    "Merchandising": [
        "Merchandiser",
        "Retail Merchandiser",
        "Visual Merchandiser",
        "Fashion Merchandiser",
        "Buying Merchandiser",
        "Merchandising Manager",
        "Product Merchandiser",
        "Export Merchandiser",
    ],
    "Store Operations": [
        "Store Manager",
        "Store Executive",
        "Store Supervisor",
        "Store Keeper",
        "Store Operations Manager",
        "Retail Store Executive",
        "Inventory Store Executive",
        "Assistant Store Manager",
    ],
    "Ecommerce": [
        "Ecommerce Executive",
        "Ecommerce Manager",
        "Marketplace Executive",
        "Catalog Executive",
        "Product Listing Executive",
        "Ecommerce Operations Executive",
        "Online Sales Executive",
        "Ecommerce Analyst",
        "Ecommerce Coordinator",
    ],
    "Marketplace Operations": [
        "Marketplace Executive",
        "Marketplace Manager",
        "Amazon Marketplace Executive",
        "Flipkart Marketplace Executive",
        "Catalog Manager",
        "Product Listing Executive",
        "Marketplace Operations Analyst",
        "Seller Support Executive",
    ],
    "Healthcare": [
        "Healthcare Executive",
        "Healthcare Administrator",
        "Hospital Administrator",
        "Patient Care Executive",
        "Medical Officer",
        "Healthcare Manager",
        "Healthcare Coordinator",
        "Medical Records Executive",
        "Healthcare Consultant",
    ],
    "Medical": [
        "Doctor",
        "Medical Officer",
        "Resident Medical Officer",
        "Physician",
        "Surgeon",
        "Dentist",
        "Medical Consultant",
        "Medical Representative",
        "Medical Advisor",
        "Medical Coordinator",
    ],
    "Nursing": [
        "Nurse",
        "Staff Nurse",
        "Registered Nurse",
        "ICU Nurse",
        "Emergency Nurse",
        "OT Nurse",
        "Nursing Assistant",
        "Nursing Supervisor",
        "Head Nurse",
        "Home Care Nurse",
    ],
    "Pharmacy": [
        "Pharmacist",
        "Pharmacy Assistant",
        "Pharmacy Manager",
        "Clinical Pharmacist",
        "Hospital Pharmacist",
        "Retail Pharmacist",
        "Pharmacy Sales Executive",
        "Drug Safety Associate",
        "Pharma Executive",
    ],
    "Clinical Research": [
        "Clinical Research Associate",
        "Clinical Research Coordinator",
        "Clinical Data Manager",
        "Clinical Trial Assistant",
        "Medical Writer",
        "Clinical Project Manager",
        "Pharmacovigilance Associate",
        "Clinical Research Scientist",
    ],
    "Laboratory": [
        "Lab Technician",
        "Laboratory Assistant",
        "Lab Manager",
        "Medical Lab Technician",
        "Pathology Technician",
        "Quality Lab Analyst",
        "Research Lab Assistant",
        "Microbiologist",
        "Chemist",
    ],
    "Education": [
        "Teacher",
        "Lecturer",
        "Professor",
        "Academic Coordinator",
        "Education Counselor",
        "School Administrator",
        "Principal",
        "Curriculum Developer",
        "Education Consultant",
        "Tutor",
    ],
    "Teaching": [
        "Teacher",
        "Primary Teacher",
        "Secondary Teacher",
        "Math Teacher",
        "Science Teacher",
        "English Teacher",
        "Computer Teacher",
        "Subject Teacher",
        "Online Tutor",
        "Assistant Professor",
    ],
    "Training": [
        "Trainer",
        "Corporate Trainer",
        "Technical Trainer",
        "Soft Skills Trainer",
        "Sales Trainer",
        "Process Trainer",
        "Product Trainer",
        "Fitness Trainer",
        "Language Trainer",
        "Training Coordinator",
    ],
    "Academic Counselling": [
        "Academic Counselor",
        "Education Counselor",
        "Admission Counselor",
        "Career Counselor",
        "Student Counselor",
        "Course Counselor",
        "Academic Advisor",
        "Study Abroad Counselor",
    ],
    "Student Support": [
        "Student Support Executive",
        "Student Coordinator",
        "Student Success Executive",
        "Academic Support Executive",
        "Student Relationship Executive",
        "Student Service Executive",
        "Student Helpdesk Executive",
    ],
    "Hospitality": [
        "Hospitality Executive",
        "Hospitality Manager",
        "Guest Relations Executive",
        "Front Office Executive",
        "Hotel Receptionist",
        "Housekeeping Executive",
        "Food and Beverage Executive",
        "Banquet Manager",
    ],
    "Hotel Management": [
        "Hotel Manager",
        "Front Office Manager",
        "Receptionist",
        "Guest Relations Manager",
        "Housekeeping Manager",
        "Restaurant Manager",
        "Room Service Executive",
        "Hotel Operations Manager",
    ],
    "Travel and Tourism": [
        "Travel Consultant",
        "Travel Executive",
        "Tour Operator",
        "Tour Manager",
        "Ticketing Executive",
        "Visa Executive",
        "Travel Coordinator",
        "Holiday Consultant",
        "Tour Guide",
    ],
    "Food and Beverage": [
        "F&B Executive",
        "F&B Manager",
        "Restaurant Manager",
        "Chef",
        "Cook",
        "Waiter",
        "Barista",
        "Kitchen Supervisor",
        "Food Safety Officer",
        "Catering Manager",
    ],
    "Real Estate": [
        "Real Estate Executive",
        "Real Estate Agent",
        "Property Consultant",
        "Property Manager",
        "Sales Manager Real Estate",
        "Leasing Executive",
        "Real Estate Broker",
        "Site Sales Executive",
        "CRM Real Estate Executive",
    ],
    "Construction": [
        "Construction Manager",
        "Site Engineer",
        "Site Supervisor",
        "Project Engineer",
        "Civil Engineer",
        "Construction Worker",
        "Planning Engineer",
        "Quantity Surveyor",
        "Safety Officer",
        "Construction Project Manager",
    ],
    "Architecture": [
        "Architect",
        "Junior Architect",
        "Senior Architect",
        "Architectural Designer",
        "Landscape Architect",
        "Interior Architect",
        "Draftsman",
        "AutoCAD Designer",
        "BIM Architect",
    ],
    "Interior Design": [
        "Interior Designer",
        "Interior Design Consultant",
        "Interior Architect",
        "Furniture Designer",
        "Space Planner",
        "Modular Kitchen Designer",
        "AutoCAD Interior Designer",
        "3D Interior Visualizer",
    ],
    "Banking": [
        "Bank Officer",
        "Bank Manager",
        "Relationship Manager",
        "Branch Manager",
        "Cashier",
        "Credit Officer",
        "Loan Officer",
        "Operations Officer",
        "Banking Sales Executive",
        "KYC Officer",
    ],
    "Insurance": [
        "Insurance Advisor",
        "Insurance Agent",
        "Insurance Sales Executive",
        "Insurance Manager",
        "Claims Executive",
        "Underwriter",
        "Policy Servicing Executive",
        "Risk Insurance Analyst",
        "Bancassurance Executive",
    ],
    "Investment": [
        "Investment Analyst",
        "Investment Advisor",
        "Portfolio Manager",
        "Equity Research Analyst",
        "Mutual Fund Advisor",
        "Wealth Manager",
        "Financial Planner",
        "Stock Broker",
        "Investment Banking Analyst",
    ],
    "Risk Management": [
        "Risk Analyst",
        "Risk Manager",
        "Credit Risk Analyst",
        "Market Risk Analyst",
        "Operational Risk Manager",
        "Fraud Risk Analyst",
        "Risk Consultant",
        "Enterprise Risk Manager",
    ],
    "Loan and Credit": [
        "Loan Officer",
        "Credit Officer",
        "Credit Analyst",
        "Loan Sales Executive",
        "Mortgage Executive",
        "Loan Processor",
        "Collection Executive",
        "Credit Manager",
        "Loan Verification Executive",
    ],
    "Media": [
        "Media Executive",
        "Media Planner",
        "Media Manager",
        "Social Media Manager",
        "Content Producer",
        "News Producer",
        "Media Analyst",
        "Media Buyer",
        "Digital Media Executive",
    ],
    "Journalism": [
        "Journalist",
        "Reporter",
        "News Reporter",
        "Editor",
        "Sub Editor",
        "News Anchor",
        "Correspondent",
        "Photojournalist",
        "Content Journalist",
        "Investigative Journalist",
    ],
    "Publishing": [
        "Publishing Executive",
        "Editor",
        "Copy Editor",
        "Proofreader",
        "Publishing Manager",
        "Book Editor",
        "Editorial Assistant",
        "Layout Editor",
        "Publication Coordinator",
    ],
    "Event Management": [
        "Event Executive",
        "Event Manager",
        "Event Coordinator",
        "Wedding Planner",
        "Corporate Event Manager",
        "Event Planner",
        "Event Sales Executive",
        "Production Coordinator",
        "Venue Manager",
    ],
    "Security": [
        "Security Guard",
        "Security Officer",
        "Security Supervisor",
        "Security Manager",
        "Safety Officer",
        "Surveillance Operator",
        "CCTV Operator",
        "Security Incharge",
        "Bouncer",
    ],
    "Facility Management": [
        "Facility Executive",
        "Facility Manager",
        "Facility Supervisor",
        "Maintenance Supervisor",
        "Housekeeping Manager",
        "Admin Facility Executive",
        "Building Manager",
        "Facility Coordinator",
    ],
    "Housekeeping": [
        "Housekeeping Staff",
        "Housekeeping Executive",
        "Housekeeping Supervisor",
        "Housekeeping Manager",
        "Room Attendant",
        "Cleaner",
        "Janitor",
        "Housekeeping Attendant",
    ],
    "BPO": [
        "BPO Executive",
        "Customer Care Executive",
        "Voice Process Executive",
        "Non Voice Process Executive",
        "Process Associate",
        "Call Center Executive",
        "Team Leader BPO",
        "BPO Manager",
        "Quality Analyst BPO",
    ],
    "KPO": [
        "KPO Executive",
        "Research Analyst",
        "Data Analyst",
        "Business Research Analyst",
        "Financial Research Analyst",
        "Market Research Analyst",
        "Process Analyst",
        "Knowledge Analyst",
        "KPO Team Leader",
    ],
    "Telecalling": [
        "Telecaller",
        "Telecalling Executive",
        "Telesales Executive",
        "Customer Calling Executive",
        "Outbound Calling Executive",
        "Inbound Calling Executive",
        "Call Center Executive",
        "Lead Generation Executive",
        "Telemarketing Executive",
    ],
    "Data Entry": [
        "Data Entry Operator",
        "Data Entry Executive",
        "Computer Operator",
        "Typing Operator",
        "Back Office Data Entry Executive",
        "Excel Data Entry Operator",
        "Online Data Entry Operator",
        "Data Processing Executive",
    ],
    "Back Office": [
        "Back Office Executive",
        "Back Office Assistant",
        "Back Office Coordinator",
        "Operations Executive",
        "Documentation Executive",
        "Data Processing Executive",
        "Admin Support Executive",
        "MIS Executive",
    ],
    "Government": [
        "Government Officer",
        "Clerk",
        "Administrative Officer",
        "Public Service Officer",
        "Data Entry Operator",
        "Project Officer",
        "Field Officer",
        "Program Officer",
        "Government Consultant",
    ],
    "Public Sector": [
        "Public Sector Officer",
        "PSU Engineer",
        "Administrative Executive",
        "Public Relations Officer",
        "Public Sector Manager",
        "Operations Officer",
        "Public Policy Executive",
        "Field Coordinator",
    ],
    "NGO": [
        "NGO Coordinator",
        "Program Coordinator",
        "Program Manager",
        "Field Coordinator",
        "Fundraising Executive",
        "Social Worker",
        "Community Mobilizer",
        "Project Officer",
        "NGO Manager",
    ],
    "Social Work": [
        "Social Worker",
        "Community Worker",
        "Field Worker",
        "Counselor",
        "Program Officer",
        "Community Development Officer",
        "Welfare Officer",
        "Case Worker",
        "Outreach Worker",
    ],
    "Agriculture": [
        "Agriculture Officer",
        "Agronomist",
        "Farm Manager",
        "Agriculture Engineer",
        "Field Officer Agriculture",
        "Crop Advisor",
        "Soil Scientist",
        "Horticulture Officer",
        "Agriculture Sales Executive",
    ],
    "Food Processing": [
        "Food Processing Executive",
        "Food Technologist",
        "Food Safety Officer",
        "Production Executive Food",
        "Quality Analyst Food",
        "Food Processing Supervisor",
        "Packaging Executive",
        "Food Plant Manager",
    ],
    "Energy": [
        "Energy Engineer",
        "Renewable Energy Engineer",
        "Solar Engineer",
        "Energy Analyst",
        "Power Plant Engineer",
        "Energy Consultant",
        "Electrical Energy Engineer",
        "Wind Energy Engineer",
        "Energy Manager",
    ],
    "Oil and Gas": [
        "Oil and Gas Engineer",
        "Petroleum Engineer",
        "Drilling Engineer",
        "Pipeline Engineer",
        "Process Engineer",
        "Refinery Operator",
        "HSE Officer",
        "Oil Field Operator",
        "Gas Plant Operator",
    ],
    "Telecom": [
        "Telecom Engineer",
        "Telecom Technician",
        "RF Engineer",
        "Network Engineer Telecom",
        "Telecom Support Engineer",
        "Tower Technician",
        "Fiber Optic Technician",
        "Telecom Project Manager",
        "NOC Engineer Telecom",
    ],
    "Automobile": [
        "Automobile Engineer",
        "Automotive Technician",
        "Service Advisor",
        "Vehicle Mechanic",
        "AutoCAD Design Engineer",
        "Automobile Sales Executive",
        "Workshop Manager",
        "Quality Engineer Automobile",
        "Production Engineer Automobile",
    ],
    "Aviation": [
        "Aircraft Maintenance Engineer",
        "Cabin Crew",
        "Ground Staff",
        "Airport Operations Executive",
        "Airline Ticketing Executive",
        "Flight Attendant",
        "Pilot",
        "Aviation Security Officer",
        "Ramp Officer",
    ],
    "Marine": [
        "Marine Engineer",
        "Marine Technician",
        "Deck Officer",
        "Marine Surveyor",
        "Shipping Officer",
        "Port Operations Executive",
        "Marine Electrician",
        "Naval Architect",
        "Seafarer",
    ],
    "Shipping": [
        "Shipping Executive",
        "Shipping Manager",
        "Logistics Executive",
        "Export Documentation Executive",
        "Freight Forwarding Executive",
        "Cargo Executive",
        "Port Operations Executive",
        "Shipping Coordinator",
        "Customs Executive",
    ],
    "Sports": [
        "Sports Coach",
        "Sports Trainer",
        "Fitness Coach",
        "Sports Manager",
        "Sports Coordinator",
        "Athletic Trainer",
        "Sports Analyst",
        "Sports Event Manager",
        "Physical Education Teacher",
    ],
    "Fitness": [
        "Fitness Trainer",
        "Personal Trainer",
        "Gym Trainer",
        "Yoga Instructor",
        "Zumba Instructor",
        "Fitness Consultant",
        "Gym Manager",
        "Strength Coach",
        "Nutrition Coach",
    ],
    "Beauty and Wellness": [
        "Beautician",
        "Beauty Therapist",
        "Hair Stylist",
        "Makeup Artist",
        "Spa Therapist",
        "Wellness Consultant",
        "Salon Manager",
        "Nail Artist",
        "Skin Therapist",
    ],
    "Fashion": [
        "Fashion Designer",
        "Fashion Consultant",
        "Fashion Stylist",
        "Fashion Merchandiser",
        "Apparel Designer",
        "Textile Designer",
        "Fashion Buyer",
        "Pattern Maker",
        "Boutique Manager",
    ],
    "Textile": [
        "Textile Designer",
        "Textile Engineer",
        "Textile Merchandiser",
        "Fabric Manager",
        "Quality Analyst Textile",
        "Production Manager Textile",
        "Weaving Supervisor",
        "Dyeing Master",
        "Garment Technologist",
    ],
    "Jewellery": [
        "Jewellery Designer",
        "Jewellery Sales Executive",
        "Goldsmith",
        "Diamond Grader",
        "Jewellery Merchandiser",
        "Jewellery Store Manager",
        "CAD Jewellery Designer",
        "Gemologist",
        "Jewellery Production Executive",
    ],
    "Printing and Packaging": [
        "Printing Operator",
        "Packaging Executive",
        "Packaging Designer",
        "Print Production Executive",
        "Printing Supervisor",
        "Packaging Manager",
        "Prepress Operator",
        "Quality Inspector Packaging",
        "Graphic Prepress Designer",
    ],
    "Others": [
        "Intern",
        "Trainee",
        "Fresher",
        "Management Trainee",
        "Graduate Trainee",
        "Consultant",
        "Coordinator",
        "Executive",
        "Assistant",
        "Supervisor",
        "Manager",
        "Team Leader",
        "Freelancer",
        "Part Time Worker",
    ],
}

# ===========================================================================
# Text normalisation
# ===========================================================================

def _normalise(text):
    """Lowercase and collapse punctuation so patterns match naturally."""
    text = str(text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#. ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _unique(roles):
    """De-duplicate by normalised form, keeping the first spelling and order.

    Freshersworld and Shine both validate the plan as a permutation of
    itself and reject any plan holding the same string twice, so every list
    this module hands out goes through here.
    """
    seen = set()
    out = []
    for role in roles:
        key = _normalise(role)
        if key and key not in seen:
            seen.add(key)
            out.append(role)
    return out


def _ngrams(norm, max_words=4):
    """Contiguous word runs of a normalised title, longest first.

    "staff nurse icu" -> ["staff nurse icu", "staff nurse", "nurse icu",
                          "staff", "nurse", "icu"]

    Used to recognise a role family inside a longer title without scanning
    the whole 1,100-entry corpus for every row: a title has a handful of
    words, so this is a fixed number of set lookups.
    """
    words = norm.split()
    grams = []
    for size in range(min(max_words, len(words)), 0, -1):
        for start in range(0, len(words) - size + 1):
            grams.append(" ".join(words[start:start + size]))
    return grams


# ===========================================================================
# Seniority
# ===========================================================================

# A title carrying any of these cannot be a 0-year job. "lead generation" is
# excluded because "Lead Generation Executive" is a sales job, not a lead.
_SENIOR_TITLE = re.compile(
    r"\b("
    r"senior|sr|lead(?!\s+generation)|head|chief|principal|director|"
    r"vp|vice president|president|manager|architect|partner|"
    r"cto|cio|coo|ceo|cxo"
    r")\b",
    re.IGNORECASE,
)

# "Architect" means seniority in IT and an entry-level profession everywhere
# else, so the architect half of the rule is skipped for these departments.
ARCHITECT_IS_ENTRY_LEVEL_DEPARTMENTS = frozenset({
    "Architecture",
    "Interior Design",
    "Construction",
    "Real Estate",
    "Design",
})

_ARCHITECT_ONLY = re.compile(r"\barchitect\b", re.IGNORECASE)


def is_senior_title(title, department=""):
    """True when a title is too senior to ever be a fresher vacancy."""
    norm = _normalise(title)
    if not norm:
        return False
    if department in ARCHITECT_IS_ENTRY_LEVEL_DEPARTMENTS:
        stripped = _ARCHITECT_ONLY.sub(" ", norm)
        return bool(_SENIOR_TITLE.search(stripped))
    return bool(_SENIOR_TITLE.search(norm))


# A title that announces itself as a fresher vacancy. Track B regardless of
# department, and never rejected.
_FRESHER_SIGNAL = re.compile(
    r"\b("
    r"fresher|freshers|trainee|trainees|intern|interns|internship|"
    r"apprentice|apprenticeship|entry level|graduate engineer trainee|"
    r"management trainee|campus hire|walk in|0 to 1 year"
    r")\b",
    re.IGNORECASE,
)


# ===========================================================================
# TRACK B - derived views of the fresher corpus
# ===========================================================================

FRESHER_DEPARTMENTS = list(FRESHER_ROLES_BY_DEPARTMENT)


def fresher_roles_by_department():
    """The corpus as the crawl plan will use it, department by department.

    Applies DROP_SENIOR_TITLES and FRESHER_ROLES_PER_DEPARTMENT. Corpus
    order is preserved, which keeps each department's commonest entry-level
    titles first and makes the per-department cap meaningful.
    """
    out = {}
    for department, roles in FRESHER_ROLES_BY_DEPARTMENT.items():
        kept = []
        for role in roles:
            if DROP_SENIOR_TITLES and is_senior_title(role, department):
                continue
            kept.append(role)
        kept = _unique(kept)
        if FRESHER_ROLES_PER_DEPARTMENT:
            kept = kept[:int(FRESHER_ROLES_PER_DEPARTMENT)]
        if kept:
            out[department] = kept
    return out


def build_fresher_plan():
    """Every fresher-plausible title, round-robin across all departments.

    Round-robin and not department-by-department. All three scrapers do
    shuffle the plan once per cycle, so in a healthy run the order here is
    not what they crawl - but each of them falls back to THIS order when a
    shuffle cannot be validated or persisted (Freshersworld and Shine say so
    in as many words: "using canonical order"). A department-major canonical
    order would mean that a fallback run finished Accounts in every city
    before it ever reached Nursing. One title per department per pass means
    any prefix of the plan covers all 116 departments.
    """
    by_department = fresher_roles_by_department()
    columns = list(by_department.values())
    plan = []
    depth = 0
    longest = max((len(column) for column in columns), default=0)
    while depth < longest:
        for column in columns:
            if depth < len(column):
                plan.append(column[depth])
        depth += 1
    return _unique(plan)


# ===========================================================================
# TRACK A - derived views
# ===========================================================================

_PRIORITY_KEYS = frozenset(_normalise(role) for role in PRIORITY_ROLES)

# The 68 target-audience titles minus the 8 that are priority profiles in
# their own right: exactly 60, the mandated 30%.
OTHER_TARGET_AUDIENCE_ROLES = [
    role for role in TARGET_AUDIENCE_ROLES
    if _normalise(role) not in _PRIORITY_KEYS
]


def build_target_audience_plan(include_high_demand=True):
    """Track A only: 100 priority + 60 other target + 40 trending IT = 200."""
    groups = [PRIORITY_ROLES, OTHER_TARGET_AUDIENCE_ROLES]
    if include_high_demand:
        groups.append(TRENDING_IT_ROLES)
    return _unique(role for group in groups for role in group)


TRACK_A_ROLES = build_target_audience_plan()
_TRACK_A_KEYS = frozenset(_normalise(role) for role in TRACK_A_ROLES)


# ===========================================================================
# The crawl plan
# ===========================================================================

def _interleave(primary, secondary):
    """Spread `primary` evenly through `secondary`, both orders preserved.

    Same reason as build_fresher_plan()'s round-robin: this is the order a
    run falls back to when its shuffle cannot be validated or persisted. A
    plan that read "all of Track A, then all of Track B" would, on that
    path, serve the target audience for a long time and freshers not at all
    until a full cycle completed. Spreading Track A through Track B means
    any prefix holds both audiences in the proportion the whole plan has.
    """
    primary = list(primary)
    secondary = list(secondary)
    if not primary:
        return secondary
    if not secondary:
        return primary

    step = len(secondary) / float(len(primary))
    out = []
    taken = 0
    for position, item in enumerate(primary):
        out.append(item)
        upto = int(round((position + 1) * step))
        out.extend(secondary[taken:upto])
        taken = upto
    out.extend(secondary[taken:])
    return out


# Built plans, keyed by the four inputs that decide them. Building one means
# normalising about 1,500 titles and running the seniority rule over every
# one, which measures ~20ms - and ShineScraper calls build_role_plan() six
# times before the first request goes out. The plan is a pure function of
# the data above, so the result is simply kept.
#
# Mutating FRESHER_ROLES_BY_DEPARTMENT at runtime (no scraper does) means
# clearing this: target_audience_roles._PLAN_CACHE.clear().
_PLAN_CACHE = {}


def build_role_plan(include_high_demand=True, include_freshers=True):
    """The ordered crawl plan: Track A interleaved through Track B.

    Shape:
      * the first PRIORITY_HEAD_SIZE priority keywords, in front, so a cold
        start or a reset checkpoint begins on the priority profiles;
      * then the rest of Track A spread evenly through Track B.

    Every entry is unique (Shine rejects a plan with repeats) and no role
    from either track can go missing - the tail of this function proves it
    and repairs the plan rather than shipping an incomplete one.

    include_high_demand=False drops the 40 trending IT keywords.
    include_freshers=False gives the Track A plan on its own, which is what
    the portal crawled before freshers were in scope.
    """
    cache_key = (
        bool(include_high_demand),
        bool(include_freshers),
        bool(DROP_SENIOR_TITLES),
        FRESHER_ROLES_PER_DEPARTMENT,
    )
    cached = _PLAN_CACHE.get(cache_key)
    if cached is not None:
        # A copy: Freshersworld and Shine shuffle what they are handed.
        return list(cached)

    track_a = build_target_audience_plan(include_high_demand=include_high_demand)
    if not include_freshers:
        _PLAN_CACHE[cache_key] = list(track_a)
        return track_a

    track_a_keys = frozenset(_normalise(role) for role in track_a)
    track_b = [
        role for role in build_fresher_plan()
        if _normalise(role) not in track_a_keys
    ]

    head = track_a[:PRIORITY_HEAD_SIZE]
    rest = track_a[PRIORITY_HEAD_SIZE:]
    plan = _unique(head + _interleave(rest, track_b))

    # Coverage guard. A reordering bug must never silently shrink the plan,
    # and raising here would take the whole scraper down, so anything that
    # went missing is appended instead.
    present = set(_normalise(role) for role in plan)
    for role in track_a + track_b:
        if _normalise(role) not in present:
            present.add(_normalise(role))
            plan.append(role)

    _PLAN_CACHE[cache_key] = list(plan)
    return plan


def role_plan_split():
    """(track_a_count, other_count, track_a_percent) - for the startup log.

    Still a 3-tuple with the same meaning it always had: how much of the plan
    is the audience that matters most, and how much is everything else. The
    three scrapers unpack it directly, so the shape cannot change.
    """
    plan = build_role_plan()
    total = len(plan)
    target = sum(1 for role in plan if _normalise(role) in _TRACK_A_KEYS)
    other = total - target
    percent = round((target * 100.0) / total, 1) if total else 0.0
    return target, other, percent


def role_plan_breakdown():
    """Full diagnostics: counts and percentages of every group in the plan."""
    plan = build_role_plan()
    priority_keys = _PRIORITY_KEYS
    other_keys = frozenset(_normalise(r) for r in OTHER_TARGET_AUDIENCE_ROLES)
    trending_keys = frozenset(_normalise(r) for r in TRENDING_IT_ROLES)

    priority = other = trending = fresher = 0
    for role in plan:
        key = _normalise(role)
        if key in priority_keys:
            priority += 1
        elif key in other_keys:
            other += 1
        elif key in trending_keys:
            trending += 1
        else:
            fresher += 1

    track_a = priority + other + trending
    total = len(plan)

    def share(count, base):
        return round((count * 100.0) / base, 1) if base else 0.0

    return {
        "total": total,
        "track_a": track_a,
        "track_b": fresher,
        "priority": priority,
        "other_target": other,
        "trending_it": trending,
        "track_a_percent_of_plan": share(track_a, total),
        "track_b_percent_of_plan": share(fresher, total),
        "priority_percent_of_track_a": share(priority, track_a),
        "other_target_percent_of_track_a": share(other, track_a),
        "trending_percent_of_track_a": share(trending, track_a),
        "departments": len(fresher_roles_by_department()),
        "unique": len(plan) == len(set(plan)),
    }


# ===========================================================================
# Departments
# ===========================================================================

def _build_role_to_department():
    """Normalised role -> department name.

    The corpus provides the non-IT departments. Track A is layered on top and
    wins, because an IT keyword belongs to IT even when the same word appears
    in another department's list ("Business Analyst", for instance).
    """
    mapping = {}
    for department, roles in FRESHER_ROLES_BY_DEPARTMENT.items():
        for role in roles:
            key = _normalise(role)
            if key and key not in mapping:
                mapping[key] = department
    for role in TRACK_A_ROLES:
        key = _normalise(role)
        if key:
            mapping[key] = DEFAULT_DEPARTMENT
    return mapping


_ROLE_TO_DEPARTMENT = _build_role_to_department()


def role_department(role, default=DEFAULT_DEPARTMENT):
    """The department a role or job title belongs to.

    Exact match first, then the longest role family inside the text, then the
    default. The three scrapers call this with the keyword they searched, so
    the exact match is what normally answers.
    """
    norm = _normalise(role)
    if not norm:
        return default
    found = _ROLE_TO_DEPARTMENT.get(norm)
    if found:
        return found
    for gram in _ngrams(norm):
        found = _ROLE_TO_DEPARTMENT.get(gram)
        if found:
            return found
    return default


# ===========================================================================
# Row filtering
# ===========================================================================

# A clear IT signal. A title matching any of these is never rejected, no
# matter what else it contains. This is what keeps "Network Security
# Engineer" from being caught by the "security guard" pattern and
# "IT Recruiter"-style false positives from removing real IT rows.
_IT_OVERRIDE = re.compile(
    r"\b("
    r"it support|technical support|help ?desk|service desk|desktop support|"
    r"end user|system admin|systems admin|server admin|linux|windows server|"
    r"network|noc|infrastructure|infra|cloud|azure|aws|gcp|devops|sre|"
    r"site reliability|kubernetes|docker|vmware|citrix|active directory|"
    r"middleware|websphere|weblogic|storage|backup|virtualisation|"
    r"virtualization|software|developer|programmer|engineer.*(java|python|"
    r"\.net|node|react|angular)|full stack|frontend|front end|backend|"
    r"back end|database|dba|sql server|oracle dba|data engineer|"
    r"data analyst|data scien|machine learning|artificial intelligence|"
    r"cyber ?security|"
    r"information security|soc analyst|penetration test|qa engineer|"
    r"test engineer|automation test|sdet|salesforce|sap |service ?now|"
    r"application support|it operations|it engineer|it executive|"
    r"it administrator|it technician|it analyst|it manager|"
    r"m365|o365|office 365|microsoft 365|intune|sccm|endpoint|sysadmin"
    r")\b",
    re.IGNORECASE,
)

# Occupations that serve neither audience. Reached only after the two
# whitelists and the seniority rule have had their say, so this list no
# longer decides the fate of a fresher row - it is the last net for text
# that matches nothing the portal knows about.
_NON_IT = re.compile(
    r"\b("
    # Sales / business development / insurance
    r"sales executive|sales officer|sales manager|sales representative|"
    r"field sales|inside sales|business development executive|"
    r"business development manager|bde|telecaller|tele caller|telecalling|"
    r"insurance advisor|policy advisor|relationship manager|"
    r"branch manager|territory manager|area sales|channel partner|"
    r"loan officer|collection executive|recovery agent|"
    # Finance / accounting / banking
    r"accountant|accounts executive|accounts assistant|accounts payable|"
    r"accounts receivable|book ?keeper|taxation|gst |audit assistant|"
    r"internal auditor|statutory audit|cashier|bank teller|"
    r"financial analyst|equity research|credit analyst|underwriter|"
    r"chartered accountant|company secretary|"
    # HR / admin / office
    r"hr executive|hr manager|hr generalist|human resource|recruiter|"
    r"talent acquisition|payroll executive|receptionist|front office|"
    r"office assistant|office boy|admin executive|administrative assistant|"
    r"personal assistant|data entry|back office|"
    # Marketing / creative / content
    r"digital marketing|seo executive|social media|content writer|"
    r"copywriter|content creator|graphic designer|video editor|"
    r"video maker|photographer|animator|brand manager|"
    r"marketing executive|marketing manager|public relations|"
    # Logistics / warehouse / field
    r"warehouse|logistics|supply chain|delivery boy|delivery executive|"
    r"driver|courier|dispatch|store keeper|storekeeper|inventory executive|"
    r"procurement|purchase executive|"
    # Education
    # NOTE: no bare "principal" -- "Principal Engineer" is an IT seniority
    # title, not a school principal.
    r"teacher|tutor|lecturer|professor|faculty|school principal|"
    r"academic counsel|admission counsel|trainer \(non|"
    # Healthcare
    r"nurse|nursing|doctor|physician|surgeon|pharmacist|"
    r"medical representative|lab technician|radiolog|physiotherap|"
    r"dental|paramedic|ward boy|"
    # Core (non-software) engineering / manufacturing
    r"civil engineer|mechanical engineer|electrical engineer|"
    r"electronics engineer|instrumentation engineer|chemical engineer|"
    r"production engineer|maintenance engineer|site engineer|"
    r"quality inspector|cnc |welder|fitter|machinist|draughtsman|"
    r"autocad|hvac|"
    # Legal / facilities / hospitality / security
    r"lawyer|advocate|paralegal|legal executive|legal associate|"
    r"housekeeping|security guard|chef|cook|waiter|steward|"
    r"hotel management|travel consultant|"
    # BPO / voice
    r"bpo|voice process|customer care|customer service executive|"
    r"customer support executive|call center|call centre|"
    r"process associate|non voice"
    r")\b",
    re.IGNORECASE,
)

# Single words too generic to identify a role on their own. A corpus title of
# one word is only allowed into the whitelist if it is not one of these, so
# "Engineer" cannot whitelist every row ever scraped while "Nurse",
# "Trainee" and "Cashier" still can.
_GENERIC_SINGLE_WORDS = frozenset({
    "engineer", "developer", "manager", "executive", "officer", "analyst",
    "consultant", "associate", "specialist", "technician", "assistant",
    "coordinator", "operator", "supervisor", "advisor", "adviser", "agent",
    "professional", "representative", "expert", "administrator", "architect",
    "lead", "head", "staff", "operations", "support", "services", "service",
})


def _build_fresher_title_keys():
    """Normalised role families the portal serves as fresher jobs.

    Senior titles are left out whatever DROP_SENIOR_TITLES says: this set
    answers "is this an entry-level role family", and is_out_of_scope_title()
    handles seniority separately.
    """
    keys = set()
    for department, roles in FRESHER_ROLES_BY_DEPARTMENT.items():
        for role in roles:
            key = _normalise(role)
            if not key:
                continue
            if is_senior_title(role, department):
                continue
            if " " not in key and key in _GENERIC_SINGLE_WORDS:
                continue
            keys.add(key)
    return frozenset(keys)


_FRESHER_TITLE_KEYS = _build_fresher_title_keys()


def is_out_of_scope_title(title):
    """True when a job title serves neither audience, so the row is dropped.

    A whitelist with two tracks, in this order:

      1. blank            -> keep. A missing title is uncertain, not junk,
                             and the row still carries a URL and a company.
      2. clear IT signal  -> keep (Track A). Unchanged from the IT-only
                             version of this filter.
      3. known role family, exactly
                          -> keep (Track B). "Staff Nurse", "Cashier",
                             "Accounts Assistant" are all real fresher jobs
                             on this portal now.
      4. says fresher     -> keep (Track B). "Trainee", "Fresher", "Intern",
                             "Apprentice", "Entry Level" in any department.
      5. senior title     -> drop. Neither audience is served by a
                             "Senior Staff Nurse" or an "Area Sales Manager":
                             Track A is IT and was already kept at step 2,
                             and Track B is 0-year by definition.
      6. role family inside a longer title
                          -> keep (Track B). "Staff Nurse ICU".
      7. known non-IT occupation
                          -> drop. The old blocklist, now the last net.
      8. anything else    -> keep. Unrecognised is not the same as unwanted,
                             and this is what the filter did before.

    WHAT THIS CANNOT DO: the scrapers call it with a bare job title, so it
    cannot see experience or salary and cannot enforce "0 years" or
    "Rs 4 LPA and above". An experienced non-IT row whose title looks
    entry-level therefore still reaches the portal. classify_job() below is
    the row-level version, ready for the day that becomes a problem.
    """
    norm = _normalise(title)
    if not norm:
        return False
    if _IT_OVERRIDE.search(norm):
        return False
    if norm in _FRESHER_TITLE_KEYS:
        return False
    if _FRESHER_SIGNAL.search(norm):
        return False
    if _SENIOR_TITLE.search(norm):
        return True
    for gram in _ngrams(norm):
        if gram in _FRESHER_TITLE_KEYS:
            return False
    return bool(_NON_IT.search(norm))


# The name the three scrapers import. Kept as an alias so no call site has to
# change; is_out_of_scope_title() is what it now actually means.
is_non_it_title = is_out_of_scope_title


# ===========================================================================
# Row-level criteria - DORMANT (see STRICT_EXPERIENCE_MODE)
# ===========================================================================
# Everything below is written, tested and unused. It enforces what a job
# title cannot express:
#
#   Track A   1 to 5 years and Rs 4 LPA and above  (hiring criteria)
#   Track B   0 years                              (a fresher job)
#
# To switch it on, set STRICT_EXPERIENCE_MODE = True and pass the whole row
# instead of the title at the one call site in each scraper:
#
#   JobDataScraper.py / ShineScraper.py, in remove_already_saved_jobs():
#       OLD:  if is_non_it_title(title):
#       NEW:  if is_out_of_scope_row(job):
#
#   find_naukri_job.py, in append_detail_to_excel():
#       OLD:  if title and is_non_it_title(title):
#       NEW:  if is_out_of_scope_row(row):
#
# The experience fields are already on the row at all three of those points
# (experience_min_years / experience_max_years / experience_required), so
# nothing else has to be collected first.
# ===========================================================================

def _to_float(value):
    """First number in a value, or None. Handles '0 - 3 years' and '4.5'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def row_experience_years(row):
    """(min_years, max_years) from a scraped row; either may be None."""
    if not isinstance(row, dict):
        return None, None
    low = _to_float(row.get("experience_min_years"))
    high = _to_float(row.get("experience_max_years"))
    if low is None and high is None:
        text = str(row.get("experience_required") or "")
        numbers = re.findall(r"\d+(?:\.\d+)?", text)
        if numbers:
            low = float(numbers[0])
            high = float(numbers[1]) if len(numbers) > 1 else low
    return low, high


def row_salary_lpa(row):
    """Annual salary in lakhs, or None when the row does not disclose one.

    Rows carry either lakhs ("4.5") or rupees per year ("450000"), so a
    value above 1,000 is read as rupees and converted.
    """
    if not isinstance(row, dict):
        return None
    for field in ("salary_min", "salary_max"):
        value = _to_float(row.get(field))
        if value is None or value <= 0:
            continue
        return value / 100000.0 if value > 1000 else value
    return None


def classify_job(row):
    """"target_audience", "fresher" or "out_of_scope" for a scraped row."""
    if not isinstance(row, dict):
        return "out_of_scope"

    title = row.get("job_title", "")
    low, high = row_experience_years(row)
    salary = row_salary_lpa(row)

    is_it = bool(_IT_OVERRIDE.search(_normalise(title)))

    # A fresher vacancy: nothing above 0 years is asked for. An undisclosed
    # range counts as a fresher job only when the title says so.
    if low is not None and low <= FRESHER_MAX_EXPERIENCE_YEARS:
        if not is_out_of_scope_title(title):
            return "fresher"
    if low is None and _FRESHER_SIGNAL.search(_normalise(title)):
        return "fresher"

    # The target audience: IT, 1 to 5 years, Rs 4 LPA and above. A missing
    # salary is not held against the row - most portals hide it - but a
    # disclosed salary below the floor is.
    if is_it:
        experience_ok = (
            low is None
            or (low <= TARGET_MAX_EXPERIENCE_YEARS
                and (high is None or high >= TARGET_MIN_EXPERIENCE_YEARS))
        )
        salary_ok = salary is None or salary >= TARGET_MIN_SALARY_LPA
        if experience_ok and salary_ok:
            return "target_audience"

    return "out_of_scope"


def is_out_of_scope_row(row):
    """Row-level replacement for is_non_it_title(). True means drop.

    Falls back to the title-only filter whenever STRICT_EXPERIENCE_MODE is
    off, so swapping the call sites early is harmless.
    """
    if not isinstance(row, dict):
        return False
    if not STRICT_EXPERIENCE_MODE:
        return is_out_of_scope_title(row.get("job_title", ""))
    return classify_job(row) == "out_of_scope"


# ===========================================================================
# Self-report:  python3 target_audience_roles.py
# ===========================================================================

def _self_report():
    plan = build_role_plan()
    stats = role_plan_breakdown()
    by_department = fresher_roles_by_department()

    print("=" * 74)
    print("ROLE PLAN: target audience + freshers of every kind")
    print("=" * 74)
    print("Total search keywords in the plan : %d" % stats["total"])
    print("  every entry unique              : %s" % stats["unique"])
    print()
    print("TRACK A  target audience          : %4d  (%.1f%% of the plan)"
          % (stats["track_a"], stats["track_a_percent_of_plan"]))
    print("   priority job profiles          : %4d  (%.1f%% of Track A, mandate 50%%)"
          % (stats["priority"], stats["priority_percent_of_track_a"]))
    print("   other target-audience profiles : %4d  (%.1f%% of Track A, mandate 30%%)"
          % (stats["other_target"], stats["other_target_percent_of_track_a"]))
    print("   trending Indian IT roles       : %4d  (%.1f%% of Track A, mandate 20%%)"
          % (stats["trending_it"], stats["trending_percent_of_track_a"]))
    print()
    print("TRACK B  freshers, all departments: %4d  (%.1f%% of the plan)"
          % (stats["track_b"], stats["track_b_percent_of_plan"]))
    print("   departments represented        : %4d of %d"
          % (stats["departments"], len(FRESHER_ROLES_BY_DEPARTMENT)))
    print("   senior titles dropped          : %s" % DROP_SENIOR_TITLES)
    print("   cap per department             : %s"
          % (FRESHER_ROLES_PER_DEPARTMENT or "none (all titles)"))
    print()
    print("role_plan_split()                 : %r" % (role_plan_split(),))
    print("first 12 keywords                 :")
    for role in plan[:12]:
        print("   %-42s -> %s" % (role, role_department(role)))
    print()
    print("filter spot-check (True = dropped):")
    samples = [
        "Azure Administrator",
        "Desktop Support Engineer",
        "Staff Nurse",
        "Accounts Assistant",
        "Graduate Engineer Trainee",
        "Senior Staff Nurse",
        "Area Sales Manager",
        "Security Guard",
        "",
    ]
    for title in samples:
        print("   %-28s %s" % (repr(title), is_non_it_title(title)))
    print()
    print("departments with the fewest titles:")
    smallest = sorted(by_department.items(), key=lambda kv: len(kv[1]))[:5]
    for department, roles in smallest:
        print("   %-30s %d  (%s)"
              % (department, len(roles), ", ".join(roles[:3])))


if __name__ == "__main__":
    _self_report()
