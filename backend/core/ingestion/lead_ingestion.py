import requests
import json
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from backend.core.onboarding.onboarding_agent import ICPOutput
import os
from dotenv import load_dotenv

load_dotenv(override=True)


if not os.getenv("APOLLO_API_KEY"):
    raise ValueError("APOLLO_API_KEY not found in environment variables")

if not os.getenv("APOLLO_PEOPLE_SEARCH_URL"):
    raise ValueError("APOLLO_PEOPLE_SEARCH_URL not found in environment variables")

if not os.getenv("APOLLO_PEOPLE_ENRICH_URL"):
    raise ValueError("APOLLO_PEOPLE_ENRICH_URL not found in environment variables")

if not os.getenv("PROSPEO_API_KEY"):
    raise ValueError("PROSPEO_API_KEY not found in environment variables")

if not os.getenv("PROSPEO_PEOPLE_SEARCH_URL"):
    raise ValueError("PROSPEO_PEOPLE_SEARCH_URL not found in environment variables")

if not os.getenv("PROSPEO_PEOPLE_ENRICH_URL"):
    raise ValueError("PROSPEO_PEOPLE_ENRICH_URL not found in environment variables")

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_PEOPLE_SEARCH_URL = os.getenv("APOLLO_PEOPLE_SEARCH_URL")
APOLLO_PEOPLE_ENRICH_URL = os.getenv("APOLLO_PEOPLE_ENRICH_URL")

PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY")
PROSPEO_PEOPLE_SEARCH_URL = os.getenv("PROSPEO_PEOPLE_SEARCH_URL")
PROSPEO_PEOPLE_ENRICH_URL = os.getenv("PROSPEO_PEOPLE_ENRICH_URL")



# Prospeo Seniority Mapping from Apollo values
# Apollo value to Prospeo seniority mapping
SENIORITY_MAP = {
    "owner":     "Founder/Owner",
    "founder":   "Founder/Owner",
    "c_suite":   "C-Suite",
    "partner":   "Partner",
    "vp":        "Vice President",
    "head":      "Head",
    "director":  "Director",
    "manager":   "Manager",
    "senior":    "Senior",
    "entry":     "Entry",
    "intern":    "Intern",
}

# Full valid Prospeo industry list
PROSPEO_VALID_INDUSTRIES = {
    "IT Services and IT Consulting",
    "Construction",
    "Business Consulting and Services",
    "General Retail",
    "Advertising Services",
    "Real Estate",
    "Software Development",
    "Medical Practices",
    "Financial Services",
    "Technology, Information and Internet",
    "Restaurants",
    "Hospitals and Health Care",
    "Wellness and Fitness Services",
    "Design Services",
    "Non-profit Organizations",
    "Individual and Family Services",
    "Hospitality",
    "Professional Training and Coaching",
    "Food and Beverage Services",
    "Education Administration Programs",
    "Consumer Services",
    "Accounting",
    "Civic and Social Organizations",
    "Architecture and Planning",
    "Entertainment Providers",
    "Retail Apparel and Fashion",
    "Higher Education",
    "Insurance",
    "Legal Services",
    "General Manufacturing",
    "Events Services",
    "Travel Arrangements",
    "Human Resources Services",
    "Law Practice",
    "Media Production and Publishing",
    "Staffing and Recruiting",
    "Marketing Services",
    "Renewable Energy",
    "Research Services",
    "Facilities Services",
    "Environmental Services",
    "Telecommunications",
    "Transportation, Logistics, Supply Chain and Storage",
    "E-Learning Providers",
    "Oil, Gas, and Mining",
    "Venture Capital and Private Equity Principals",
    "Investment Management",
    "Civil Engineering",
    "Primary and Secondary Education",
    "Medical Equipment Manufacturing",
    "Public Relations and Communications Services",
    "Mental Health Care",
    "Chemical Manufacturing",
    "Pharmaceutical Manufacturing",
    "Utilities",
    "Information Services",
    "Security and Investigations",
    "Banking",
    "Biotechnology Research",
    "Computer and Network Security",
    "Computer Games",
    "Market Research",
    "Mechanical or Industrial Engineering",
    "Strategic Management Services",
    "Consumer Goods",
    "Engineering Services",
    "Investment, Funds and Trusts",
    "Human Resources",
    "Computer Hardware",
    "Defense and Space Manufacturing",
    "Semiconductor Manufacturing",
    "Capital Markets",
    "Wireless Services",
    "Professional Services",
    "Social Networking Platforms",
    "Internet Marketplace Platforms",
    "Blockchain Services",
    "Data Infrastructure and Analytics",
    "Home Health Care Services",
    "Packaging and Containers",
    "Mobile Gaming Apps",
    "Administrative and Support Services",
    "Nanotechnology Research",
    "Robotics Engineering",
    "Data Security Software Products",
    "Climate Technology Product Manufacturing",
    "Executive Search Services",
}

# Normalized Lead output (same shape regardless of provider) 

class LeadResult(BaseModel):
    name: Optional[str] = Field(None, description="Full name of the lead.")
    first_name: Optional[str] = Field(None, description="First name of the lead.")
    last_name: Optional[str] = Field(None, description="Last name of the lead.")
    title: Optional[str] = Field(None, description="Current job title of the lead.")
    seniority: Optional[str] = Field(None, description="Seniority level of the lead (e.g., C-Suite, Director, Manager).")
    email: Optional[str] = Field(None, description="Work email address of the lead.")
    email_status: Optional[str] = Field(None, description="Email verification status (e.g., VERIFIED, UNVERIFIED).")
    phone: Optional[str] = Field(None, description="Mobile or direct phone number of the lead.")
    company: Optional[str] = Field(None, description="Name of the company the lead currently works at.")
    company_size: Optional[int] = Field(None, description="Number of employees at the lead's current company.")
    industry: Optional[str] = Field(None, description="Industry sector of the lead's current company.")
    location: Optional[str] = Field(None, description="City where the lead is located.")
    country: Optional[str] = Field(None, description="Country where the lead is located.")
    linkedin: Optional[str] = Field(None, description="LinkedIn profile URL of the lead.")
    provider_id: Optional[str] = Field(None, description="Unique ID assigned to the lead by the data provider.")
    provider: Optional[str] = Field(None, description="Data provider used to source this lead (e.g., prospeo, apollo).")
    type: Optional[str] = Field(None, description="Type of the lead (business, individual, both).")


# BASE PROVIDER INTERFACE — all providers must implement this
class LeadProvider(ABC):

    @abstractmethod
    def search(self, icp: ICPOutput, fetch_all: bool = False) -> list[dict]:
        """Search for people matching the ICP. Returns raw results."""
        pass

    @abstractmethod
    def enrich(self, person: dict, enrich_mobile: bool = False) -> LeadResult:
        """Enrich a single person record to get email/phone."""
        pass

    def get_leads(
        self,
        icp: ICPOutput,
        fetch_all: bool = False,
        enrich_mobile: bool = False,
        test_mode: bool = False,        # if True, only enriches 1 record
        use_mock: bool = False,
    ) -> list[LeadResult]:
        """Full pipeline: search → enrich → return leads."""

        if use_mock:
            from backend.core.mock_data import MOCK_ENRICHED_LEADS
            print(f"\n Mock mode — returning {len(MOCK_ENRICHED_LEADS)} mock leads.")
            return MOCK_ENRICHED_LEADS

        print(f"\n Provider: {self.__class__.__name__}")
        people = self.search(icp, fetch_all=fetch_all)

        if not people:
            print("No people found. Try broadening your ICP.")
            return []

        print(people)	
        # Preview first 3 raw results
        print(f"\n--- Sample Search Results (first 3 of {len(people)}) ---")
        for p in people[:3]:
            print(json.dumps(self._preview(p), indent=2))

        # In test mode, only enrich 1 record
        to_enrich = people[:1] if test_mode else people
        print(f"\n  Enriching {len(to_enrich)} record(s)...")

        leads = []
        for i, person in enumerate(to_enrich, 1):
            print(f"   [{i}/{len(to_enrich)}] Enriching: {self._get_name(person)}")
            lead = self.enrich(person, enrich_mobile=enrich_mobile, lead_type=icp.target_type)
            if lead:
                leads.append(lead)
            time.sleep(0.3)

        print(f"\n Done. Leads enriched: {len(leads)}")
        return leads

    @abstractmethod
    def _preview(self, person: dict) -> dict:
        """Return a small preview dict for logging."""
        pass

    @abstractmethod
    def _get_name(self, person: dict) -> str:
        """Extract name from raw search result for logging."""
        pass


# PROSPEO PROVIDER
class ProspeoProvider(LeadProvider):


    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("PROSPEO_API_KEY is required")
        self.headers = {
            "X-KEY": api_key,
            "Content-Type": "application/json"
        }

    def _icp_to_filters(self, icp: ICPOutput) -> dict:
        filters = {}

        if icp.job_titles:
            filters["person_job_title"] = {
                "include": icp.job_titles,
                "match_only_exact_job_titles": False  # broader matching
            }

        if icp.seniority:
            mapped = list({
                SENIORITY_MAP[s] for s in icp.seniority
                if s in SENIORITY_MAP
            })
            if mapped:
                filters["person_seniority"] = {"include": mapped}

        # Locations — skip global/worldwide
        clean_locations = [
            loc for loc in icp.locations
            if loc.lower() not in ["global", "global/multiple regions", "worldwide"]
        ]
        if clean_locations:
            filters["person_location_search"] = {"include": clean_locations}

        # Company headcount — plain array (NOT include/exclude dict)
        if icp.company_size_min is not None or icp.company_size_max is not None:
            min_e = icp.company_size_min or 1
            max_e = icp.company_size_max or 99999999
            ranges = self._map_headcount(min_e, max_e)
            if ranges:
                filters["company_headcount_range"] = ranges  

        if icp.industry:
            valid = [i for i in icp.industry if i in PROSPEO_VALID_INDUSTRIES]
            invalid = [i for i in icp.industry if i not in PROSPEO_VALID_INDUSTRIES]

            if invalid:
                print(f"    Skipping invalid industries: {invalid}")

            if valid:
                filters["company_industry"] = {"include": valid}
            else:
                print("    No valid industries — industry filter skipped.")

        if icp.tech_stack:
            filters["company_technology"] = {"include": icp.tech_stack}

        if icp.funding_status:
            filters["company_funding"] = {"stage": icp.funding_status}

        # Only verified emails
        filters["person_contact_details"] = {"email": ["VERIFIED"]}

        return filters

    def _map_headcount(self, min_e: int, max_e: int) -> list[str]:
        """Map min/max employee count to Prospeo headcount range enums."""
        # Prospeo exact ranges from docs:
        # 1-10, 11-20, 21-50, 51-100, 101-200, 201-500,
        # 501-1000, 1001-2000, 2001-5000, 5001-10000, 10000+
        all_ranges = [
            (1,     10,       "1-10"),
            (11,    20,       "11-20"),
            (21,    50,       "21-50"),
            (51,    100,      "51-100"),
            (101,   200,      "101-200"),
            (201,   500,      "201-500"),
            (501,   1000,     "501-1000"),
            (1001,  2000,     "1001-2000"),
            (2001,  5000,     "2001-5000"),
            (5001,  10000,    "5001-10000"),
            (10001, 99999999, "10000+"),
        ]
        return [
            label for (lo, hi, label) in all_ranges
            if lo <= max_e and hi >= min_e
        ]

    def search(self, icp: ICPOutput, fetch_all: bool = False) -> list[dict]:
        url = f"{PROSPEO_PEOPLE_SEARCH_URL}"
        filters = self._icp_to_filters(icp)
        all_people = []
        page = 1
        # fetch_all=False → only page 1 (25 results)
        # fetch_all=True  → paginate up to 1000 pages

        print(f"\n Prospeo search (fetch_all={fetch_all})...")
        print(f"   Titles    : {icp.job_titles}")
        print(f"   Seniority : {icp.seniority}")
        print(f"   Locations : {icp.locations}")
        print(f"   Employees : {icp.company_size_min} - {icp.company_size_max}")

        while True:
            payload = {"filters": filters, "page": page}
            response = requests.post(url, headers=self.headers, json=payload)

            if response.status_code == 429:
                print(" Rate limited. Waiting 60s...")
                time.sleep(60)
                continue

            data = response.json()

            if data.get("error"):
                error_code = data.get("error_code")
                if error_code == "NO_RESULTS":
                    print(f" No more results at page {page}.")
                else:
                    print(f" Search Error: {error_code} — {data}")
                break

            results = data.get("results", [])
            if not results:
                break

            all_people.extend(results)
            pagination = data.get("pagination", {})
            total_pages = pagination.get("total_page", 1)
            total_count = pagination.get("total_count", "?")

            print(f" Page {page}/{total_pages}: fetched {len(results)} | Total so far: {len(all_people)} / {total_count}")

            # Stop after page 1 if not fetching all
            if not fetch_all:
                print(" Stopped at page 1 (fetch_all=False).")
                break

            if page >= total_pages or page >= 1000:
                print(" Reached last page.")
                break

            page += 1
            time.sleep(0.5)

        print(f"\n Step 1 complete. Total found: {len(all_people)}")
        return all_people

    def enrich(self, person: dict, enrich_mobile: bool = False, retries: int = 3, lead_type: str = None) -> LeadResult:
        url = f"{PROSPEO_PEOPLE_ENRICH_URL}"

        person_data = person.get("person", {})
        person_id = person_data.get("person_id")

        if not person_id:
            print("    No person_id, skipping.")
            return None

        payload = {
            "only_verified_email": True,
            "enrich_mobile": enrich_mobile,
            "data": {"person_id": person_id}
        }

        for attempt in range(1, retries + 1):
            response = requests.post(url, headers=self.headers, json=payload)

            if response.status_code == 429:
                print(f"    Rate limited. Attempt {attempt}/{retries}. Waiting 60s...")
                time.sleep(60)
                continue

            data = response.json()

            if data.get("error"):
                error_code = data.get("error_code")
                if error_code == "NO_MATCH":
                    print(f"   No match for person_id: {person_id}")
                else:
                    print(f"   Enrich error: {error_code}")
                return None

            p = data.get("person", {})
            c = data.get("company") or {}
            email_obj = p.get("email") or {}
            mobile_obj = p.get("mobile") or {}
            location_obj = p.get("location") or {}

            return LeadResult(
                name=p.get("full_name"),
                first_name=p.get("first_name"),
                last_name=p.get("last_name"),
                title=p.get("current_job_title"),
                seniority=None,  # comes from job_history if needed
                email=email_obj.get("email") if email_obj.get("revealed") else None,
                email_status=email_obj.get("status"),
                phone=mobile_obj.get("mobile") if mobile_obj.get("revealed") else None,
                company=c.get("name"),
                company_size=c.get("employee_count"),
                industry=c.get("industry"),
                location=location_obj.get("city"),
                country=location_obj.get("country"),
                linkedin=p.get("linkedin_url"),
                provider_id=p.get("person_id"),
                provider="prospeo",
                type=lead_type
            )

        print(f"   Enrich failed after {retries} attempts.")
        return None

    def _preview(self, person: dict) -> dict:
        p = person.get("person", {})
        c = person.get("company") or {}
        return {
            "person_id": p.get("person_id"),
            "name": p.get("full_name"),
            "title": p.get("current_job_title"),
            "company": c.get("name"),
            "location": (p.get("location") or {}).get("city"),
            "linkedin": p.get("linkedin_url"),
        }

    def _get_name(self, person: dict) -> str:
        return person.get("person", {}).get("full_name", "Unknown")


# APOLLO PROVIDER
class ApolloProvider(LeadProvider):

    def __init__(self, api_key: str):
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}"
        }

    def _icp_to_params(self, icp: ICPOutput) -> dict:
        params = {}

        if icp.job_titles:
            params["person_titles[]"] = icp.job_titles

        if icp.seniority:
            params["person_seniorities[]"] = icp.seniority

        clean_locations = [
            loc for loc in icp.locations
            if loc.lower() not in ["global", "global/multiple regions", "worldwide"]
        ]
        if clean_locations:
            params["person_locations[]"] = clean_locations

        if icp.company_size_min is not None and icp.company_size_max is not None:
            params["organization_num_employees_ranges[]"] = [
                f"{icp.company_size_min},{icp.company_size_max}"
            ]
        elif icp.company_size_min is not None:
            params["organization_num_employees_ranges[]"] = [
                f"{icp.company_size_min},1000000"
            ]
        elif icp.company_size_max is not None:
            params["organization_num_employees_ranges[]"] = [
                f"1,{icp.company_size_max}"
            ]

        if icp.tech_stack:
            params["currently_using_any_of_technology_uids[]"] = [
                t.lower().replace(" ", "_").replace(".", "_")
                for t in icp.tech_stack
            ]

        params["contact_email_status[]"] = ["verified"]
        return params

    def search(self, icp: ICPOutput, fetch_all: bool = False) -> list[dict]:
        url = "https://api.apollo.io/api/v1/mixed_people/api_search"
        all_people = []
        page = 1
        per_page = 25 if not fetch_all else 100

        base_params = self._icp_to_params(icp)

        print(f"\n Apollo search (fetch_all={fetch_all})...")

        while True:
            params = {**base_params, "page": page, "per_page": per_page}
            response = requests.post(url, headers=self.headers, params=params)

            if response.status_code == 429:
                print("  Rate limited. Waiting 60s...")
                time.sleep(60)
                continue

            if response.status_code != 200:
                print(f" Search Error {response.status_code}: {response.text}")
                break

            data = response.json()
            people = data.get("people", [])

            if not people:
                break

            all_people.extend(people)
            total = data.get("pagination", {}).get("total_entries", "?")
            print(f" Page {page}: fetched {len(people)} | Total: {len(all_people)} / {total}")

            if not fetch_all:
                print(" Stopped at page 1 (fetch_all=False).")
                break

            if len(people) < per_page or page >= 500:
                break

            page += 1
            time.sleep(0.5)

        print(f"\n Step 1 complete. Total found: {len(all_people)}")
        return all_people

    def enrich(self, person: dict, enrich_mobile: bool = False, retries: int = 3, lead_type: str = None) -> LeadResult:
        url = "https://api.apollo.io/api/v1/people/match"

        payload = {
            "id": person.get("id"),
            "reveal_personal_emails": True,
            "reveal_phone_number": enrich_mobile,
        }

        for attempt in range(1, retries + 1):
            response = requests.post(url, headers=self.headers, json=payload)

            if response.status_code == 429:
                print(f"    Rate limited. Attempt {attempt}/{retries}. Waiting 60s...")
                time.sleep(60)
                continue

            if response.status_code != 200:
                print(f"   Enrich Error {response.status_code}")
                return None

            p = response.json().get("person", {})
            return LeadResult(
                name=p.get("name"),
                title=p.get("title"),
                seniority=p.get("seniority"),
                email=p.get("email"),
                phone=p.get("sanitized_phone"),
                company=p.get("organization", {}).get("name"),
                company_size=p.get("organization", {}).get("num_employees"),
                industry=p.get("organization", {}).get("industry"),
                location=p.get("city"),
                country=p.get("country"),
                linkedin=p.get("linkedin_url"),
                provider_id=p.get("id"),
                provider="apollo",
                type=lead_type
            )

        print(f"   Enrich failed after {retries} attempts.")
        return None

    def _preview(self, person: dict) -> dict:
        return {
            "id": person.get("id"),
            "name": person.get("name"),
            "title": person.get("title"),
            "company": person.get("organization", {}).get("name"),
            "location": person.get("city"),
            "linkedin": person.get("linkedin_url"),
        }

    def _get_name(self, person: dict) -> str:
        return person.get("name", "Unknown")


# PROVIDER FACTORY — switch providers here
def get_provider(name: Literal["prospeo", "apollo"]) -> LeadProvider:
    if name == "prospeo":
        api_key = os.getenv("PROSPEO_API_KEY")
        if not api_key:
            raise ValueError("PROSPEO_API_KEY not found in .env")
        return ProspeoProvider(api_key)

    elif name == "apollo":
        api_key = os.getenv("APOLLO_API_KEY")
        if not api_key:
            raise ValueError("APOLLO_API_KEY not found in .env")
        return ApolloProvider(api_key)

    else:
        raise ValueError(f"Unknown provider: {name}. Choose 'prospeo' or 'apollo'.")


# EXAMPLE USAGE
if __name__ == "__main__":

    stripe_icp = ICPOutput(
        target_type="business",
        industry=["Financial Services", "Technology"],
        company_size_min=51,
        company_size_max=10000,
        funding_status=None,
        job_titles=["CFO", "Fintech Manager", "Product Manager"],
        seniority=["c_suite", "vp", "director", "manager"],
        locations=["Global"],
        tech_stack=None,
        demographics=None
    )

    andela_icp = ICPOutput(
        target_type="business",
        industry=["AI/ML", "Tech services", "Software development"],
        company_size_min=50,
        company_size_max=None,
        funding_status=None,
        job_titles=["AI engineers", "Data scientists", "ML engineers", "AI team leads"],
        seniority=["owner", "founder", "c_suite", "partner", "vp", "head", "director"],
        locations=["Global"],
        tech_stack=None,
        demographics=None
    )

    # Switch provider here: "prospeo" or "apollo"
    provider = get_provider("prospeo")

    leads = provider.get_leads(
        icp=stripe_icp,
        fetch_all=False,     # False = first 25 only | True = all pages
        enrich_mobile=False, # True = costs 10 credits per person
        test_mode=True,       # True = only enrich 1 record (for testing)
        use_mock=True
    )

    print(leads)

    print("\n===== FINAL LEADS =====")
    if not leads:
        print(" No leads returned.")
    else:
        for lead in leads:
            print(json.dumps(lead.model_dump(exclude_none=True), indent=2))