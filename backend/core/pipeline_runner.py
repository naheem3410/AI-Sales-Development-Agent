"""
pipeline_runner.py
------------------
The pipeline coordinator. Chains all agents in sequence using the infrastructure layer.
This is NOT an LLM agent — it is a plain Python orchestrator.

Flow:
    Onboarding → [Orchestration slot] → Ingestion → Query Generation
    → Enrichment → Qualification → Email Generation

Each step:
    1. Reads from the database/queue
    2. Calls the agent
    3. Persists results to the database
    4. Sends a message to the next queue
    5. Updates campaign status

The orchestration slot is a pass-through today.
When activated, the orchestration agent intercepts between Onboarding and Ingestion.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.config.settings import settings
from backend.core.enums import (
    AgentName, QueueName, CampaignStatus, LeadStatus,
    MessageStatus, QualificationDecision
)
from backend.core.messages import (
    PipelineMessage, OrchestrationMetadata,
    OnboardingPayload, OrchestrationPayload, IngestionPayload,
    QueryGeneratorPayload, EnrichmentPayload, QualificationPayload, EmailPayload
)
from backend.infrastructure.factory import get_db, get_queue, get_storage

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_correlation_id() -> str:
    return str(uuid.uuid4())


class PipelineRunner:
    """
    Coordinates the full SDA pipeline for a single campaign run.
    Inject your agent functions at construction time — the runner
    calls them and handles all persistence and messaging.
    """

    def __init__(self):
        self.db = get_db()
        self.queue = get_queue()
        self.storage = get_storage()

    # ── Step 0: Initialise Campaign 

    def init_campaign(
        self,
        user_id: str,
        campaign_name: str,
        website_url: str,
        company_name: Optional[str] = None,
    ) -> dict:
        """
        Create a new campaign and initialise the orchestration slot.
        Returns the campaign dict.
        """
        campaign = self.db.create_campaign(
            user_id=user_id,
            name=campaign_name,
            website_url=website_url,
            company_name=company_name,
        )
        # Provision the orchestration slot immediately
        self.db.init_orchestration_state(
            campaign_id=campaign["id"],
            user_id=user_id
        )
        logger.info(
            f"[PipelineRunner] Campaign {campaign['id']} initialised "
            f"for user {user_id}"
        )
        return campaign

    # ── Step 1: Onboarding 

    async def run_onboarding(
        self,
        campaign_id: str,
        user_id: str,
        website_url: str,
        company_name: Optional[str] = None,
    ) -> PipelineMessage:
        """Run the onboarding agent and persist ICP + product brief."""

        correlation_id = _new_correlation_id()

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.ONBOARDING_RUNNING,
            agent=AgentName.ONBOARDING,
            notes="Onboarding agent started"
        )

        try:
            # Import here to keep agent code decoupled from infrastructure
            from backend.config.settings import settings
            from backend.core.onboarding.onboarding_agent import OnboardingAgentInput

            onboarding_input = OnboardingAgentInput(
                website_url=website_url,
                company_name=company_name,
            )
            if settings.use_onboarding_orchestrator:
                from backend.core.onboarding.onboarding_orchestrator import (
                    run_onboarding_orchestrator,
                )

                result = await run_onboarding_orchestrator(onboarding_input)
            else:
                from backend.core.onboarding.onboarding_agent import run_onboarding_agent

                result = await run_onboarding_agent(onboarding_input)

            # Persist ICP and product brief
            icp_data = result.icp.model_dump()
            brief_data = result.product_brief.model_dump()

            self.db.save_icp(campaign_id, user_id, {
                **icp_data,
                "confidence_score": result.confidence_score,
                "missing_fields": result.missing_fields,
            })
            self.db.save_product_brief(campaign_id, user_id, brief_data)

            # Build outbound message
            payload = OnboardingPayload(
                website_url=website_url,
                company_name=company_name,
                icp=icp_data,
                product_brief=brief_data,
                confidence_score=result.confidence_score,
                missing_fields=result.missing_fields,
            )

            message = PipelineMessage(
                correlation_id=correlation_id,
                user_id=user_id,
                campaign_id=campaign_id,
                source_agent=AgentName.ONBOARDING,
                target_agent=AgentName.ORCHESTRATION,   # orchestration slot
                queue=QueueName.ONBOARDING_COMPLETE,
                campaign_status_on_send=CampaignStatus.ONBOARDING_COMPLETE,
                payload=payload.model_dump(),
            )

            self.queue.send(message)
            self._log_message(message)

            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.ONBOARDING_COMPLETE,
                agent=AgentName.ONBOARDING,
                from_status=CampaignStatus.ONBOARDING_RUNNING,
                notes=f"ICP and product brief saved. Confidence: {result.confidence_score}"
            )

            logger.info(f"[PipelineRunner] Onboarding complete for campaign {campaign_id}")
            return message

        except Exception as e:
            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.ONBOARDING_FAILED,
                failure_reason=str(e),
                agent=AgentName.ONBOARDING,
            )
            raise

    # ── Orchestration Slot (pass-through) 

    def run_orchestration_passthrough(
        self,
        onboarding_message: PipelineMessage,
        provider: str = "prospeo",
        fetch_all: bool = False,
        enrich_mobile: bool = False,
        target_lead_count: int = 25,
    ) -> PipelineMessage:
        """
        Orchestration pass-through.
        Today: applies sensible defaults and forwards to ingestion.
        Later: replaced by the orchestration agent making these decisions.
        """
        campaign_id = onboarding_message.campaign_id

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.ORCHESTRATION_RUNNING,
            agent=AgentName.ORCHESTRATION,
            notes="Orchestration pass-through (not yet active)"
        )

        # Update orchestration state — even as a pass-through, record the decisions
        self.db.update_orchestration_state(campaign_id, {
            "provider_selected": provider,
            "fetch_all": 1 if fetch_all else 0,
            "enrich_mobile": 1 if enrich_mobile else 0,
            "target_lead_count": target_lead_count,
            "activated": 0,  # not active yet
            "notes": "Pass-through mode — decisions set by pipeline runner defaults",
        })

        # Build the orchestration output payload
        orch_payload = OrchestrationPayload(
            onboarding=onboarding_message.payload,
            provider_selected=provider,
            fetch_all=fetch_all,
            enrich_mobile=enrich_mobile,
            target_lead_count=target_lead_count,
            notes="Pass-through: defaults applied",
        )

        # Carry orchestration metadata forward on all subsequent messages
        orch_meta = OrchestrationMetadata(
            decision="passthrough",
            provider_selected=provider,
            fetch_all=fetch_all,
            notes="Orchestration agent not yet active — defaults used",
        )

        message = PipelineMessage(
            correlation_id=onboarding_message.correlation_id,
            user_id=onboarding_message.user_id,
            campaign_id=campaign_id,
            source_agent=AgentName.ORCHESTRATION,
            target_agent=AgentName.INGESTION,
            queue=QueueName.ORCHESTRATION_OUT,
            orchestration=orch_meta,
            campaign_status_on_send=CampaignStatus.ORCHESTRATION_COMPLETE,
            payload=orch_payload.model_dump(),
        )

        self.queue.send(message)
        self._log_message(message)

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.ORCHESTRATION_COMPLETE,
            agent=AgentName.ORCHESTRATION,
            from_status=CampaignStatus.ORCHESTRATION_RUNNING,
            notes=f"Pass-through complete. Provider={provider}, fetch_all={fetch_all}"
        )

        return message

    # ── Step 2: Lead Ingestion 

    def run_ingestion(self, orchestration_message: PipelineMessage) -> PipelineMessage:
        """Run lead ingestion using the ICP from the onboarding payload."""

        campaign_id = orchestration_message.campaign_id
        user_id = orchestration_message.user_id
        orch_payload = orchestration_message.payload

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.INGESTION_RUNNING,
            agent=AgentName.INGESTION,
            notes="Lead ingestion started"
        )

        try:
            from backend.core.ingestion.lead_ingestion import get_provider
            from backend.core.onboarding.onboarding_agent import ICPOutput

            # Reconstruct ICP from payload
            onboarding_data = orch_payload.get("onboarding", {})
            icp = ICPOutput.model_validate(onboarding_data.get("icp", {}))

            provider_name = orch_payload.get("provider_selected", "prospeo")
            fetch_all = orch_payload.get("fetch_all", False)
            enrich_mobile = orch_payload.get("enrich_mobile", False)

            provider = get_provider(provider_name)
            leads = provider.get_leads(
                icp=icp,
                fetch_all=False,
                enrich_mobile=False,
                test_mode=False,
                use_mock=False,
            )

            if not leads:
                raise ValueError("No leads returned from provider.")

            # Persist leads
            lead_dicts = [lead.model_dump() for lead in leads]
            saved_leads = self.db.save_leads_batch(campaign_id, user_id, lead_dicts)

            # Store in storage if large batch
            if len(leads) > 50:
                self.storage.put(
                    f"{campaign_id}/ingestion/leads_raw.json",
                    lead_dicts
                )

            payload = IngestionPayload(
                provider=provider_name,
                total_leads=len(leads),
                leads=lead_dicts,
                fetch_all_used=fetch_all,
                pages_fetched=1 if not fetch_all else 0,
            )

            message = PipelineMessage(
                correlation_id=orchestration_message.correlation_id,
                user_id=user_id,
                campaign_id=campaign_id,
                source_agent=AgentName.INGESTION,
                target_agent=AgentName.ENRICHMENT,
                queue=QueueName.INGESTION_COMPLETE,
                orchestration=orchestration_message.orchestration,
                campaign_status_on_send=CampaignStatus.INGESTION_COMPLETE,
                payload=payload.model_dump(),
            )

            self.queue.send(message)
            self._log_message(message)

            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.INGESTION_COMPLETE,
                agent=AgentName.INGESTION,
                from_status=CampaignStatus.INGESTION_RUNNING,
                notes=f"Ingested {len(leads)} leads via {provider_name}"
            )

            logger.info(f"[PipelineRunner] Ingestion complete: {len(leads)} leads")
            return message

        except Exception as e:
            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.INGESTION_FAILED,
                failure_reason=str(e),
                agent=AgentName.INGESTION,
            )
            raise

    # ── Step 2b: Query Generation 

    def run_query_generation(self, ingestion_message: PipelineMessage) -> tuple:
        """
        Generate search queries for each lead.
        Returns (updated_message, leads, query_output) for the enrichment step.
        """
        from backend.core.ingestion.lead_ingestion import LeadResult
        from backend.core.query.generate_queries import generate_queries

        campaign_id = ingestion_message.campaign_id
        user_id = ingestion_message.user_id
        leads_data = ingestion_message.payload.get("leads", [])

        leads = [LeadResult.model_validate(l) for l in leads_data]
        query_output = generate_queries(leads)

        # Persist queries per lead
        db_leads = self.db.get_leads_for_campaign(campaign_id)
        lead_id_map = {i: db_lead["id"] for i, db_lead in enumerate(db_leads)}

        for i, (lead_queries, db_lead) in enumerate(zip(query_output.results, db_leads)):
            self.db.save_lead_queries(
                lead_id=db_lead["id"],
                campaign_id=campaign_id,
                user_id=user_id,
                queries=lead_queries.queries
            )
            self.db.update_lead_status(db_lead["id"], LeadStatus.QUERIED)

        logger.info(
            f"[PipelineRunner] Queries generated for {len(leads)} leads "
            f"in campaign {campaign_id}"
        )

        return leads, query_output

    # ── Step 3: Enrichment 

    async def run_enrichment(self, ingestion_message: PipelineMessage) -> PipelineMessage:
        """Run the enrichment agent on all ingested leads."""

        campaign_id = ingestion_message.campaign_id
        user_id = ingestion_message.user_id

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.ENRICHMENT_RUNNING,
            agent=AgentName.ENRICHMENT,
            notes="Enrichment agent started"
        )

        try:
            from backend.core.enrichment.enrichment_agent import run_lead_enrichment_agent

            # Generate queries first
            leads, query_output = self.run_query_generation(ingestion_message)

            result = await run_lead_enrichment_agent(
                leads=leads,
                query_output=query_output,
            )

            db_leads = self.db.get_leads_for_campaign(campaign_id)

            for enriched in result.enriched_leads:
                li = enriched.lead_index
                if li < 1 or li > len(db_leads):
                    logger.warning(
                        f"[PipelineRunner] Skipping enrichment with lead_index={li} "
                        f"(campaign has {len(db_leads)} leads)"
                    )
                    continue
                db_lead = db_leads[li - 1]
                enriched_dict = enriched.model_dump()

                # Offload large evidence to storage
                if len(enriched.raw_search_evidence) > 20:
                    s3_key = self.storage.put_enrichment_evidence(
                        campaign_id, db_lead["id"],
                        [e.model_dump() for e in enriched.raw_search_evidence]
                    )
                    enriched_dict["raw_search_evidence_s3"] = s3_key
                    enriched_dict["raw_search_evidence"] = []

                self.db.save_enrichment_result(
                    lead_id=db_lead["id"],
                    campaign_id=campaign_id,
                    user_id=user_id,
                    enrichment=enriched_dict,
                )
                self.db.update_lead_status(db_lead["id"], LeadStatus.ENRICHED)

            enriched_dicts = [e.model_dump() for e in result.enriched_leads]

            payload = EnrichmentPayload(
                total_enriched=len(result.enriched_leads),
                enriched_leads=enriched_dicts,
            )

            message = PipelineMessage(
                correlation_id=ingestion_message.correlation_id,
                user_id=user_id,
                campaign_id=campaign_id,
                source_agent=AgentName.ENRICHMENT,
                target_agent=AgentName.QUALIFICATION,
                queue=QueueName.ENRICHMENT_COMPLETE,
                orchestration=ingestion_message.orchestration,
                campaign_status_on_send=CampaignStatus.ENRICHMENT_COMPLETE,
                payload=payload.model_dump(),
            )

            self.queue.send(message)
            self._log_message(message)

            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.ENRICHMENT_COMPLETE,
                agent=AgentName.ENRICHMENT,
                from_status=CampaignStatus.ENRICHMENT_RUNNING,
                notes=f"Enriched {len(result.enriched_leads)} leads"
            )

            logger.info(f"[PipelineRunner] Enrichment complete: {len(result.enriched_leads)} leads")
            return message

        except Exception as e:
            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.ENRICHMENT_FAILED,
                failure_reason=str(e),
                agent=AgentName.ENRICHMENT,
            )
            raise

    # ── Step 4: Qualification 

    async def run_qualification(self, enrichment_message: PipelineMessage) -> PipelineMessage:
        """Run the qualification agent."""

        campaign_id = enrichment_message.campaign_id
        user_id = enrichment_message.user_id

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.QUALIFICATION_RUNNING,
            agent=AgentName.QUALIFICATION,
            notes="Qualification agent started"
        )

        try:
            from backend.core.qualification.qualification_agent import run_qualification_agent
            from backend.core.ingestion.lead_ingestion import LeadResult
            from backend.core.enrichment.enrichment_agent import LeadEnrichmentAgentOutput, LeadEnrichmentResult
            from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput, ICPOutput, ProductBriefOutput

            enriched_data = enrichment_message.payload.get("enriched_leads", [])
            enriched_leads = [LeadEnrichmentResult.model_validate(e) for e in enriched_data]

            db_leads = self.db.get_leads_for_campaign(campaign_id)
            leads = [LeadResult.model_validate(l) for l in db_leads]

            icp_data = self.db.get_icp(campaign_id)
            brief_data = self.db.get_product_brief(campaign_id)

            onboarding = OnboardingAgentOutput(
                icp=ICPOutput.model_validate(icp_data),
                product_brief=ProductBriefOutput.model_validate(brief_data),
                confidence_score=icp_data.get("confidence_score", 1.0),
                missing_fields=icp_data.get("missing_fields", []),
            )

            from backend.core.enrichment.enrichment_agent import LeadEnrichmentAgentOutput
            enrichment_output = LeadEnrichmentAgentOutput(enriched_leads=enriched_leads)

            result = await run_qualification_agent(
                leads=leads,
                enrichment_output=enrichment_output,
                onboarding=onboarding,
            )

            # Persist decisions
            all_decisions = result.approved + result.review + result.rejected
            for decision in all_decisions:
                lead_idx = decision.lead_index - 1
                if lead_idx < len(db_leads):
                    db_lead = db_leads[lead_idx]
                    self.db.save_qualification_result(
                        lead_id=db_lead["id"],
                        campaign_id=campaign_id,
                        user_id=user_id,
                        decision=decision.model_dump(),
                    )
                    status = {
                        "approved": LeadStatus.QUALIFIED,
                        "review": LeadStatus.REVIEW,
                        "rejected": LeadStatus.DISQUALIFIED,
                    }.get(decision.decision, LeadStatus.DISQUALIFIED)
                    self.db.update_lead_status(db_lead["id"], status)

            payload = QualificationPayload(
                total_approved=len(result.approved),
                total_review=len(result.review),
                total_rejected=len(result.rejected),
                approved=[d.model_dump() for d in result.approved],
                review=[d.model_dump() for d in result.review],
                rejected=[d.model_dump() for d in result.rejected],
                batch_summary=result.batch_summary,
            )

            message = PipelineMessage(
                correlation_id=enrichment_message.correlation_id,
                user_id=user_id,
                campaign_id=campaign_id,
                source_agent=AgentName.QUALIFICATION,
                target_agent=AgentName.EMAIL,
                queue=QueueName.QUALIFICATION_COMPLETE,
                orchestration=enrichment_message.orchestration,
                campaign_status_on_send=CampaignStatus.QUALIFICATION_COMPLETE,
                payload=payload.model_dump(),
            )

            self.queue.send(message)
            self._log_message(message)

            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.QUALIFICATION_COMPLETE,
                agent=AgentName.QUALIFICATION,
                from_status=CampaignStatus.QUALIFICATION_RUNNING,
                notes=(
                    f"Approved: {len(result.approved)}, "
                    f"Review: {len(result.review)}, "
                    f"Rejected: {len(result.rejected)}"
                )
            )

            logger.info(
                f"[PipelineRunner] Qualification complete — "
                f"approved={len(result.approved)}, "
                f"review={len(result.review)}, "
                f"rejected={len(result.rejected)}"
            )
            return message

        except Exception as e:
            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.QUALIFICATION_FAILED,
                failure_reason=str(e),
                agent=AgentName.QUALIFICATION,
            )
            raise

    # ── Step 5: Email Generation 

    async def run_email_generation(self, qualification_message: PipelineMessage) -> PipelineMessage:
        """Run the email copywriting agent for approved and review leads."""

        campaign_id = qualification_message.campaign_id
        user_id = qualification_message.user_id

        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.EMAIL_GENERATION_RUNNING,
            agent=AgentName.EMAIL,
            notes="Email generation started"
        )

        try:
            from backend.core.email.email_agent import run_email_copywriting_agent
            from backend.core.ingestion.lead_ingestion import LeadResult
            from backend.core.enrichment.enrichment_agent import (
                LeadEnrichmentResult,
                EnrichedProfile, SocialProfile, KeyValue,
                SearchResultItem, DiscrepancyFlag,
            )
            from backend.core.qualification.qualification_agent import LeadDecision
            from backend.core.onboarding.onboarding_agent import (
                OnboardingAgentOutput, ICPOutput, ProductBriefOutput
            )

            qual_payload = qualification_message.payload
            approved_decisions = [
                LeadDecision.model_validate(d)
                for d in qual_payload.get("approved", []) + qual_payload.get("review", [])
            ]

            if not approved_decisions:
                logger.warning(
                    f"[PipelineRunner] No approved leads for email generation "
                    f"in campaign {campaign_id}"
                )
                payload = EmailPayload(
                    total_sequences=0,
                    sequences=[],
                    batch_notes="No approved leads to write emails for."
                )
            else:
                # ── All leads for this campaign, ordered by creation 
                db_leads = self.db.get_leads_for_campaign(campaign_id)

                # 1-based lead_index → LeadResult  (matches agent convention)
                lead_map = {
                    i + 1: LeadResult.model_validate(l)
                    for i, l in enumerate(db_leads)
                }
                # 1-based lead_index -> db_lead row  (for persistence)
                db_lead_map = {i + 1: l for i, l in enumerate(db_leads)}

                approved_leads = [lead_map[d.lead_index] for d in approved_decisions]

                # ── Rebuild enrichment map from DB 
                import json as _json
                import sqlite3 as _sqlite3

                enrichment_map = {}
                for lead_index, db_lead in db_lead_map.items():
                    conn = _sqlite3.connect(self.db.db_path)
                    conn.row_factory = _sqlite3.Row
                    row = conn.execute(
                        """SELECT * FROM enrichment_results
                           WHERE lead_id = ?
                           ORDER BY created_at DESC LIMIT 1""",
                        (db_lead["id"],)
                    ).fetchone()
                    conn.close()

                    if not row:
                        continue

                    r = dict(row)

                    def _loads(val):
                        if val and isinstance(val, str):
                            try:
                                return _json.loads(val)
                            except Exception:
                                return []
                        return val or []

                    enrichment_map[lead_index] = LeadEnrichmentResult(
                        lead_index=lead_index,
                        lead_name=db_lead.get("name") or "",
                        raw_search_evidence=[
                            SearchResultItem(**e)
                            for e in _loads(r.get("raw_search_evidence")) if e
                        ],
                        enriched_data=EnrichedProfile(
                            current_title=r.get("current_title"),
                            social_links=[
                                SocialProfile(**s)
                                for s in _loads(r.get("social_links")) if s
                            ],
                            company_signals=[
                                KeyValue(**s)
                                for s in _loads(r.get("company_signals")) if s
                            ],
                            notable_achievements=_loads(r.get("notable_achievements")),
                        ),
                        discrepancies=[
                            DiscrepancyFlag(**d)
                            for d in _loads(r.get("discrepancies")) if d
                        ],
                        query_slot_coverage=[
                            KeyValue(**kv)
                            for kv in _loads(r.get("query_slot_coverage")) if kv
                        ],
                        identity_status=r.get("identity_status", "not_found"),
                        confidence_score=r.get("confidence_score", 0.0),
                        evidence_used=_loads(r.get("evidence_used")),
                        enrichment_summary=r.get("enrichment_summary") or "",
                    )

                logger.info(
                    f"[PipelineRunner] Rebuilt enrichment map: "
                    f"{len(enrichment_map)} leads from DB"
                )

                # ── Onboarding context 
                icp_data = self.db.get_icp(campaign_id)
                brief_data = self.db.get_product_brief(campaign_id)
                onboarding = OnboardingAgentOutput(
                    icp=ICPOutput.model_validate(icp_data),
                    product_brief=ProductBriefOutput.model_validate(brief_data),
                    confidence_score=icp_data.get("confidence_score", 1.0),
                    missing_fields=icp_data.get("missing_fields") or [],
                )

                user_row = self.db.get_user(user_id)
                sender_display_name = (user_row or {}).get("full_name")

                # ── Run email agent 
                result = await run_email_copywriting_agent(
                    approved_leads=approved_leads,
                    enrichment_output_map=enrichment_map,
                    decisions=approved_decisions,
                    onboarding=onboarding,
                    user_id=user_id,
                    sender_display_name=sender_display_name,
                )

                # ── Persist sequences 
                for seq in result.sequences:
                    db_lead = db_lead_map.get(seq.lead_index)
                    if not db_lead:
                        logger.warning(
                            f"[PipelineRunner] No DB lead for "
                            f"seq.lead_index={seq.lead_index} — skipping"
                        )
                        continue
                    seq_dict = seq.model_dump()
                    self.db.save_email_sequence(
                        lead_id=db_lead["id"],
                        campaign_id=campaign_id,
                        user_id=user_id,
                        sequence=seq_dict,
                    )
                    self.storage.put_email_sequence(campaign_id, db_lead["id"], seq_dict)
                    self.db.update_lead_status(db_lead["id"], LeadStatus.EMAIL_WRITTEN)

                payload = EmailPayload(
                    total_sequences=len(result.sequences),
                    sequences=[s.model_dump() for s in result.sequences],
                    batch_notes=result.batch_notes,
                )

            message = PipelineMessage(
                correlation_id=qualification_message.correlation_id,
                user_id=user_id,
                campaign_id=campaign_id,
                source_agent=AgentName.EMAIL,
                target_agent=AgentName.REPLY,          # future: Reply Agent slot
                queue=QueueName.EMAIL_COMPLETE,
                orchestration=qualification_message.orchestration,
                campaign_status_on_send=CampaignStatus.EMAIL_GENERATION_COMPLETE,
                payload=payload.model_dump(),
            )

            self.queue.send(message)
            self._log_message(message)

            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.EMAIL_GENERATION_COMPLETE,
                agent=AgentName.EMAIL,
                from_status=CampaignStatus.EMAIL_GENERATION_RUNNING,
                notes=f"Wrote {payload.total_sequences} email sequences"
            )

            logger.info(f"[PipelineRunner] Email generation complete: {payload.total_sequences} sequences")
            return message

        except Exception as e:
            self.db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.EMAIL_GENERATION_FAILED,
                failure_reason=str(e),
                agent=AgentName.EMAIL,
            )
            raise

    # ── Full Pipeline Run 

    async def run_full_pipeline(
        self,
        user_id: str,
        campaign_name: str,
        website_url: str,
        company_name: Optional[str] = None,
        provider: str = "prospeo",
        fetch_all: bool = False,
        enrich_mobile: bool = False,
        target_lead_count: int = 25,
    ) -> dict:
        """
        Run the complete pipeline end to end.
        Returns a summary dict on completion.
        """
        logger.info(f"[PipelineRunner] Starting full pipeline for {website_url}")

        # 0. Init
        campaign = self.init_campaign(user_id, campaign_name, website_url, company_name)
        campaign_id = campaign["id"]

        # 1. Onboarding
        onboarding_msg = await self.run_onboarding(
            campaign_id, user_id, website_url, company_name
        )

        # 2. Orchestration pass-through
        orch_msg = self.run_orchestration_passthrough(
            onboarding_message=onboarding_msg,
            provider=provider,
            fetch_all=fetch_all,
            enrich_mobile=enrich_mobile,
            target_lead_count=target_lead_count,
        )

        # 3. Ingestion
        ingestion_msg = self.run_ingestion(orch_msg)

        # 4. Enrichment (includes query generation)
        enrichment_msg = await self.run_enrichment(ingestion_msg)

        # 5. Qualification
        qualification_msg = await self.run_qualification(enrichment_msg)

        # 6. Email generation
        email_msg = await self.run_email_generation(qualification_msg)

        # 7. Mark complete
        self.db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.CAMPAIGN_COMPLETE,
            agent=AgentName.EMAIL,
            notes="Full pipeline completed successfully"
        )

        summary = self.db.get_campaign_summary(campaign_id)
        logger.info(f"[PipelineRunner] Pipeline complete. Summary: {summary}")
        return summary

    # ── Internal Helpers 

    def _log_message(self, message: PipelineMessage):
        """Persist a pipeline message to the audit log."""
        payload_size = len(json.dumps(message.payload))
        payload_s3_key = None

        # Offload large payloads to storage
        if payload_size > 100_000:
            payload_s3_key = self.storage.put_pipeline_payload(
                message.campaign_id, message.message_id, message.payload
            )

        self.db.log_pipeline_message({
            "id": message.message_id,
            "correlation_id": message.correlation_id,
            "user_id": message.user_id,
            "campaign_id": message.campaign_id,
            "source_agent": message.source_agent.value,
            "target_agent": message.target_agent.value,
            "queue": message.queue.value,
            "status": message.status.value,
            "campaign_status_on_send": message.campaign_status_on_send.value,
            "orchestration_metadata": message.orchestration.model_dump_json(),
            "payload_summary": f"payload_size={payload_size} bytes",
            "payload_s3_key": payload_s3_key,
            "retry_count": message.retry_count,
            "last_error": message.last_error.model_dump_json() if message.last_error else None,
            "pipeline_version": message.pipeline_version,
            "created_at": message.created_at.isoformat(),
            "processed_at": message.processed_at.isoformat() if message.processed_at else None,
            "completed_at": message.completed_at.isoformat() if message.completed_at else None,
        })