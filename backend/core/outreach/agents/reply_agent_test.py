"""Manual test harness for reply_agent — run from sda_platform root."""

import asyncio
import logging

from backend.core.outreach.agents.reply_agent import ReplyAgentInput, run_reply_agent


async def main():
    test_cases = [
        ReplyAgentInput(
            lead_id="lead-001",
            lead_name="Ar. Shamali Kather",
            lead_email="naheemquadri3410@gmail.com",
            lead_company="73 Strings",
            lead_title="Product Manager II",
            reply_subject="Re: Scaling your engineering team",
            reply_body_text=(
                "Hi, thanks for reaching out. This actually sounds interesting. "
                "We've been struggling to find good AI engineers. "
                "Can you tell me more about pricing and how fast you can get someone started?"
            ),
            original_email_number=1,
            original_subject="Scaling your engineering team at 73 Strings",
            product_name="Andela",
            product_pain="Finding senior AI/ML engineers is slow and expensive.",
            product_differentiators=[
                "Pre-vetted senior engineers",
                "AI/ML specialisation",
                "On-demand scaling — ramp up in days",
            ],
            rag_context=(
                "FAQ: Typical onboarding time is 5-7 business days. "
                "Pricing starts at $5,000/month per engineer. "
                "We specialise in AI, ML, data science, and backend engineering."
            ),
            sender_name="James",
            cal_link="https://cal.com/james/30min",
        ),
        ReplyAgentInput(
            lead_id="lead-002",
            lead_name="Michael Greenlief",
            lead_email="michael.greenlief@jackhenry.com",
            lead_company="Jack Henry",
            lead_title="Senior Technical Product Manager",
            reply_subject="Auto: Out of Office",
            reply_body_text=(
                "I am currently out of the office until December 18th. "
                "For urgent matters, please contact my colleague at admin@jackhenry.com."
            ),
            original_email_number=1,
            original_subject="Engineering capacity at Jack Henry",
            product_name="Andela",
            product_pain="Finding senior AI/ML engineers is slow and expensive.",
            product_differentiators=["Pre-vetted senior engineers"],
            rag_context=None,
            sender_name="James",
            cal_link="https://cal.com/james/30min",
        ),
        ReplyAgentInput(
            lead_id="lead-003",
            lead_name="Marshall Syahrial",
            lead_email="naheemquadri3410@gmail.com",
            lead_company="Financial Technology",
            lead_title="Principal Product Manager",
            reply_subject="Re: Engineering team",
            reply_body_text=(
                "Thanks for reaching out but I'm not the right person for this. "
                "You should speak to our CTO Bob Hutchinson — bob.hutchinson@commonsecuritization.com"
            ),
            original_email_number=2,
            original_subject="Following up on engineering capacity",
            product_name="Andela",
            product_pain="Finding senior AI/ML engineers is slow and expensive.",
            product_differentiators=["Pre-vetted senior engineers"],
            rag_context=None,
            sender_name="James",
            cal_link="https://cal.com/james/30min",
        ),
    ]

    labels = ["Interested", "OOF", "Wrong Person"]

    for label, test_input in zip(labels, test_cases):
        print(f"\n{'=' * 70}")
        print(f"Test: {label}")
        print(f"Reply: {test_input.reply_body_text[:80]}...")
        print(f"{'=' * 70}")
        try:
            output = await run_reply_agent(test_input)
            print(f"Classification : {output.classification}")
            print(f"Confidence     : {output.confidence_score:.0%}")
            print(f"Reason         : {output.classification_reason}")
            print(f"Action         : {output.recommended_action}")
            if output.drafted_response_body:
                print(f"Response       :\n{output.drafted_response_body[:300]}...")
            if output.referral:
                print(f"Referral       : {output.referral.name} <{output.referral.email}>")
            if output.resume_after_days:
                print(f"Resume in      : {output.resume_after_days} days")
            print(f"Notes          : {output.agent_notes[:100]}...")
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
