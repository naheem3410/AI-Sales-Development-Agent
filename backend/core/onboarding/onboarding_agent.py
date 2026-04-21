import asyncio
from agents.mcp import MCPServerStdio
from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



class OnboardingAgentInput(BaseModel):
    website_url: str = Field(..., description="The full URL of the company website to analyze.")
    company_name: Optional[str] = Field(None, description="The name of the company, if known.")

class ICPOutput(BaseModel):
    target_type: Literal["business", "individual", "both"] = Field(..., description="Whether the ICP targets companies or direct consumers.")
    industry: List[str] = Field(..., description="Relevant industry sectors. Use these exact values: "
        "'Software Development', 'IT Services and IT Consulting', "
        "'Technology, Information and Internet', 'Financial Services', "
        "'Hospitals and Health Care', 'Data Infrastructure and Analytics', "
        "'Business Consulting and Services', 'Staffing and Recruiting', "
        "'Marketing Services', 'Renewable Energy'.")
    # Business-specific fields
    company_size_min: Optional[int] = Field(None, description="Minimum employee count for target businesses.")
    company_size_max: Optional[int] = Field(None, description="Maximum employee count for target businesses.")
    funding_status: Optional[List[str]] = Field(None, description="Preferred funding stages (e.g., Series A, Seed).")
    # Individual/Persona fields
    job_titles: List[str] = Field(..., description="Target job titles or roles (e.g., CTO, Marketing Manager, Freelancer).")
    locations: List[str] = Field(..., description="Geographic regions where the target customers are located.")
    tech_stack: Optional[List[str]] = Field(None, description="Technologies the customer likely uses.")
    demographics: Optional[str] = Field(None, description="For individual targets: age range, interests, or specific behaviors.")
    seniority: Optional[List[Literal[
        "owner", "founder", "c_suite", "partner",
        "vp", "head", "director", "manager",
        "senior", "entry", "intern"
    ]]] = Field(
        None,
        description="Seniority levels to target."
    )

class ProductBriefOutput(BaseModel):
    product_name: str = Field(..., description="The official name of the product or service.")
    what_it_does: str = Field(..., description="A concise summary of the product's primary function.")
    who_it_is_for: str = Field(..., description="The primary audience or user persona.")
    pain_it_solves: str = Field(..., description="The specific problems or 'pain points' addressed.")
    key_differentiators: List[str] = Field(..., description="Unique selling points that set it apart from competitors.")
    ideal_customer_description: str = Field(..., description="A narrative description of the perfect customer match.")

class OnboardingAgentOutput(BaseModel):
    icp: ICPOutput
    product_brief: ProductBriefOutput
    confidence_score: float = Field(..., description="Score between 0-1 reflecting data completeness.")
    missing_fields: List[str] = Field(..., description="List of fields that couldn't be determined from the website.")


instructions = """
You are a Sales Development Strategy Expert. 

### THE "GOLDEN PATH" RULE:
You must only perform exactly TWO actions:
1. `browser_navigate` to the URL.
2. `browser_evaluate` using the JS snippet below to get the text.
3. IMMEDIATELY output the OnboardingAgentOutput.

### SCRAPE TOOL (Rule 3):
Use this JS to prevent token overflow: 
`() => { 
   return { 
     body: document.body.innerText.substring(0, 25000), 
     meta: document.querySelector('meta[name="description"]')?.content || "" 
   }; 
}`

### CRITICAL CONSTRAINTS:
- **Never repeat a tool call**: If you have the data from the first evaluate, DO NOT call it again for "more detail."
- **Stay on the homepage**: Do not click links or follow redirects to sub-pages.
- **Synthesis**:
    - Distinguish if the company targets businesses (B2B), individuals (B2C), or both.
    - For B2B: Identify target company size and funding where possible.
    - Identify the 'Job to be Done' and specific pain points the product alleviates.
- **Structured Output**: Populate the `OnboardingAgentOutput` schema. If information is truly missing from the homepage, do not hallucinate; add the field name to `missing_fields`.

Be concise and professional.
"""

playwright_args = [
        "@playwright/mcp@latest",
        "--headless",
        "--isolated", 
        "--no-sandbox",
        "--ignore-https-errors",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
]

# Configuration
playwright_params = {"command": "npx", "args": playwright_args}

async def run_onboarding_agent(user_input: OnboardingAgentInput) -> OnboardingAgentOutput:
    MODEL = "openai/gpt-4.1-nano"
    model = LitellmModel(model=MODEL)

    with trace("onboarding agent"):
        async with MCPServerStdio(params=playwright_params, client_session_timeout_seconds=60) as mcp_server_browser:
            
            # patch list_tools on the server to return only allowed tools
            allowed_names = {"browser_navigate", "browser_evaluate"}
            original_list_tools = mcp_server_browser.list_tools

            async def filtered_list_tools(*args, **kwargs):
                all_tools = await original_list_tools(*args, **kwargs)
                return [t for t in all_tools if t.name in allowed_names]

            mcp_server_browser.list_tools = filtered_list_tools

            agent = Agent(
                name="OnboardingInvestigator", 
                instructions=instructions, 
                model=model,
                mcp_servers=[mcp_server_browser],
                output_type=OnboardingAgentOutput
            )

            prompt = f"Analyze the following website and create a profile: {user_input.website_url}"
            if user_input.company_name:
                prompt += f" (Company Name: {user_input.company_name})"
            try:
                logger.info(f"Running onboarding agent for {user_input.website_url}")
                result = await Runner.run(agent, prompt, max_turns=15)
                logger.info(f"Onboarding agent completed for {user_input.website_url}")
            except MaxTurnsExceeded as e:
                logger.error(f"Onboarding agent maxturnsexceeded error for {user_input.website_url}")
                return OnboardingAgentOutput(
                    icp=ICPOutput(target_type="both", industry=[], job_titles=[], locations=[]),
                    product_brief=ProductBriefOutput(product_name="Unknown", what_it_does="N/A", who_it_is_for="N/A", pain_it_solves="N/A", key_differentiators=[], ideal_customer_description="N/A"),
                    confidence_score=0.0,
                    missing_fields=["ALL - Agent timed out due to looping or 404 errors"]
                )
            try:
                if isinstance(result.final_output,str):
                    logger.info(f"Onboarding agent output is a string for {user_input.website_url}")
                    output_data = OnboardingAgentOutput.model_validate_json(result.final_output)
                else:
                    logger.info(f"Onboarding agent output is a Pydantic model for {user_input.website_url}")
                    output_data = OnboardingAgentOutput.model_validate(result.final_output)
            except Exception as e:
                logger.error(f"Failed to validate agent output against Pydantic schema: {e}")
                raise ValueError(f"Failed to validate agent output against Pydantic schema: {e}")
            
            if result.final_output.confidence_score <= 0.2:
                logger.error(f"Result does not pass: Confidence score is too low ({output_data.confidence_score * 100}%). ")
                raise ValueError(f"Result does not pass: Confidence score is too low ({output_data.confidence_score * 100}%). "
                    f"Missing fields: {output_data.missing_fields}")
            
            return output_data

# --- TEST MAIN METHOD ---
if __name__ == "__main__":
    # Sample data for testing
    test_input = OnboardingAgentInput(
        website_url="https://www.lapo-nigeria.org/",
        company_name="Lapo"
    )

    async def main():
        print(f"Starting onboarding for: {test_input.website_url}...")
        try:
            profile = await run_onboarding_agent(test_input)
            print("\n--- ICP Results ---")
            print(f"Target Type: {profile.icp.target_type} {profile.icp}")
            print(f"Industries: {', '.join(profile.icp.industry)}")
            
            print("\n--- Product Brief ---")
            print(f"Summary: {profile.product_brief.what_it_does}")
            print(f"Differentiators: {profile.product_brief.key_differentiators}")
            
            print(f"\nConfidence: {profile.confidence_score * 100}%")
            if profile.missing_fields:
                print(f"Missing: {profile.missing_fields}")
        except Exception as e:
            print(f" Error during onboarding: {e}")

    asyncio.run(main())