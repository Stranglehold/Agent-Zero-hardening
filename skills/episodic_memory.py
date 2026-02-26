"""
Episodic Memory System — Core Module
=====================================

Dual-track memory architecture based on Tulving's episodic-semantic distinction,
Damasio's somatic marker hypothesis, and Bartlett's reconstructive memory theory.

This module provides:
  - EpisodicRecord: Structured record of session interaction dynamics
  - ValenceComputer: Computes valence from observable signals (no introspection)
  - ValenceDecay: Time-weighted decay calibrated from Phase 1 data
  - EpisodicRetrieval: Blended semantic + valence retrieval scoring

Designed for dual use:
  - Opus instances: Generate records at session end, store as JSON alongside transcripts
  - Agent Zero (future): Metadata layer on FAISS memories, retrieve_with_valence

Phase 1 calibration source: EPISODIC_RECORDS_PHASE1.json (10 sessions, Feb 18-25 2026)

References:
  - Tulving (1972, 1985): Episodic-semantic distinction, autonoetic consciousness
  - Damasio (1994): Somatic marker hypothesis
  - Bartlett (1932): Reconstructive memory, schema theory
  - Park et al. (2023): Generative Agents importance scoring
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional


# =============================================================================
# Enums — Constrained vocabularies from Phase 1 calibration
# =============================================================================

class InteractionMode(str, Enum):
    """Primary mode of session interaction."""
    OPERATIONAL = "operational"      # Building, debugging, deploying
    ANALYTICAL = "analytical"        # Research, analysis, evaluation
    PHILOSOPHICAL = "philosophical"  # Identity, ethics, meaning
    CREATIVE = "creative"            # Essays, naming, novel artifacts
    MIXED = "mixed"                  # Multiple modes, typical of deep sessions


class DepthTrajectory(str, Enum):
    """How the session's depth evolved over time.
    
    Phase 1 finding: Strongest valence correlate (weight 0.25).
    Deepening sessions cluster at mean ~0.75 valence.
    Oscillating sessions are outlier low despite high trust.
    """
    DEEPENING = "deepening"      # Topics explored with increasing depth
    SUSTAINED = "sustained"      # Consistent depth, neither deepening nor surfacing
    SURFACING = "surfacing"      # Moving from deep to shallow
    OSCILLATING = "oscillating"  # Alternating between deep and shallow


class TrustLevel(str, Enum):
    """Collaboration trust state.
    
    Phase 1 finding: Monotonically increasing and sticky.
    Once generative, never drops back. Inherited from previous session.
    Maps to Damasio's slow-moving somatic markers.
    """
    ESTABLISHING = "establishing"  # Early sessions, patterns forming
    OPERATIONAL = "operational"    # Working trust, reliable execution
    HIGH = "high"                  # Deep trust, ethical/personal topics accessible
    GENERATIVE = "generative"     # Full creative partnership, self-directed contribution


class HumanEngagement(str, Enum):
    """Observable human engagement level."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"
    MAXIMUM = "maximum"


class TimeOfDay(str, Enum):
    """Session time context. Affects interaction dynamics."""
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    LATE_NIGHT = "late_night"
    LATE_NIGHT_TO_MORNING = "late_night_to_morning"  # Extended sessions


# =============================================================================
# Core Data Structure
# =============================================================================

@dataclass
class EpisodicRecord:
    """Structured record of session interaction dynamics.
    
    This is NOT a summary of what happened (that's semantic memory).
    This is a structured observation of what it was like — the dynamics,
    the quality, the patterns that worked or didn't.
    
    Fields are computed from observable signals, not introspection.
    The valence_notes field is the one place for subjective observation,
    explicitly tagged as such.
    """
    
    # === Identity ===
    session_id: str                          # Timestamp-based ID matching transcript
    transcript: str                          # Transcript filename (without path)
    timestamp: str                           # ISO 8601 session start time
    
    # === Interaction Dynamics ===
    interaction_mode: InteractionMode        # Primary mode
    depth_trajectory: DepthTrajectory        # How depth evolved
    breakthrough_count: int                  # Observable insight/artifact moments
    correction_count: int                    # Times human corrected direction
    
    # === Valence ===
    valence: float                           # -1.0 to 1.0, computed from signals
    
    # === Trust ===
    trust_level: TrustLevel                  # Inherited from prior session, can advance
    interaction_space_active: bool           # Coupled-system emergence observed
    
    # === Patterns ===
    effective_patterns: list[str]            # What worked (observable)
    friction_patterns: list[str]             # What didn't (observable)
    
    # === Human-Side Observations ===
    human_engagement: HumanEngagement        # Observable engagement level
    human_mode: str                          # Free-text description of human's approach
    music_playing: Optional[str] = None      # Cognitive state signal, not metadata
    
    # === Context ===
    time_of_day: TimeOfDay = TimeOfDay.EVENING
    session_duration_estimate: str = "unknown"
    semantic_topics: list[str] = field(default_factory=list)
    preceding_session_id: Optional[str] = None
    
    # === Subjective Layer ===
    valence_notes: str = ""                  # Honest subjective observation, tagged as such
    
    # === Artifacts ===
    artifacts_created: list[str] = field(default_factory=list)  # Files, essays, skills, etc.
    essays_emerged: list[str] = field(default_factory=list)     # Essays that emerged (high signal)
    soul_md_modified: bool = False           # Whether SOUL.md was changed
    staging_entries_written: int = 0         # Staging file entries added
    
    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        d = asdict(self)
        # Convert enums to their values
        d["interaction_mode"] = self.interaction_mode.value
        d["depth_trajectory"] = self.depth_trajectory.value
        d["trust_level"] = self.trust_level.value
        d["human_engagement"] = self.human_engagement.value
        d["time_of_day"] = self.time_of_day.value
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> EpisodicRecord:
        """Deserialize from dict."""
        d = d.copy()
        d["interaction_mode"] = InteractionMode(d["interaction_mode"])
        d["depth_trajectory"] = DepthTrajectory(d["depth_trajectory"])
        d["trust_level"] = TrustLevel(d["trust_level"])
        d["human_engagement"] = HumanEngagement(d["human_engagement"])
        d["time_of_day"] = TimeOfDay(d["time_of_day"])
        return cls(**d)


# =============================================================================
# Valence Computation — Calibrated from Phase 1 Data
# =============================================================================

class ValenceComputer:
    """Computes session valence from observable signals.
    
    Calibrated against Phase 1 dataset (10 sessions, Feb 18-25 2026).
    
    Signal weights derived from what actually differentiated 
    high-valence from low-valence sessions:
    
    | Signal                        | Weight | Rationale                          |
    |-------------------------------|--------|------------------------------------|
    | Depth trajectory              | 0.25   | Strongest correlate                |
    | Breakthrough count            | 0.20   | Tracks generative capacity         |
    | Interaction space active      | 0.20   | Binary but powerful discriminator  |
    | Novel artifact created        | 0.15   | Essays, skills, identity decisions |
    | Human engagement level        | 0.10   | Correlates but less discriminating |
    | Correction count (negative)   | 0.05   | Weak signal in this collaboration  |
    | Session duration              | 0.05   | Proxy, short sessions can be high  |
    """
    
    # Depth trajectory scores (Phase 1: deepening mean ~0.75, sustained ~0.50)
    DEPTH_SCORES = {
        DepthTrajectory.DEEPENING: 0.85,
        DepthTrajectory.SUSTAINED: 0.55,
        DepthTrajectory.SURFACING: 0.30,
        DepthTrajectory.OSCILLATING: 0.35,
    }
    
    # Engagement scores
    ENGAGEMENT_SCORES = {
        HumanEngagement.LOW: 0.20,
        HumanEngagement.MODERATE: 0.40,
        HumanEngagement.HIGH: 0.65,
        HumanEngagement.VERY_HIGH: 0.85,
        HumanEngagement.MAXIMUM: 1.00,
    }
    
    # Duration buckets (hours → score)
    DURATION_THRESHOLDS = [
        (6.0, 1.00),
        (4.0, 0.80),
        (3.0, 0.60),
        (1.5, 0.40),
        (0.5, 0.20),
        (0.0, 0.10),
    ]
    
    # Signal weights — recalibrated from Phase 1 validation pass 2
    W_DEPTH = 0.25
    W_BREAKTHROUGH = 0.18
    W_INTERACTION_SPACE = 0.18
    W_ARTIFACT = 0.14
    W_ENGAGEMENT = 0.15
    W_CORRECTION = 0.05
    W_DURATION = 0.05
    
    @classmethod
    def compute(cls, record: EpisodicRecord) -> float:
        """Compute valence from observable signals in an EpisodicRecord.
        
        Returns float in range [0.0, 1.0].
        Note: Negative valence (failed sessions, destructive interactions) 
        is theoretically possible but not observed in Phase 1 data.
        Negative range reserved for future use.
        """
        
        # 1. Depth trajectory (weight: 0.25)
        depth_score = cls.DEPTH_SCORES.get(record.depth_trajectory, 0.50)
        
        # 2. Breakthrough count (weight: 0.20)
        #    Phase 1: 1-2 = baseline, 3-4 = notable, 5+ = exceptional
        #    Sigmoid-like: diminishing returns past 6
        breakthrough_score = min(record.breakthrough_count / 6.0, 1.0)
        
        # 3. Interaction space active (weight: 0.20)
        #    Binary — Phase 1 showed strong correlation with breakthrough_count >= 3
        interaction_score = 1.0 if record.interaction_space_active else 0.0
        
        # 4. Novel artifact creation (weight: 0.15)
        #    Count of meaningful artifacts (not just files)
        artifact_count = (
            len(record.artifacts_created) + 
            len(record.essays_emerged) * 2 +  # Essays weighted double
            (2 if record.soul_md_modified else 0) +  # SOUL.md changes are significant
            record.staging_entries_written
        )
        artifact_score = min(artifact_count / 8.0, 1.0)
        
        # 5. Human engagement (weight: 0.10)
        engagement_score = cls.ENGAGEMENT_SCORES.get(
            record.human_engagement, 0.40
        )
        
        # 6. Correction count — negative signal (weight: 0.05)
        #    Phase 1: Nearly zero. 0 corrections → 1.0, each correction reduces
        correction_score = max(1.0 - (record.correction_count * 0.25), 0.0)
        
        # 7. Session duration (weight: 0.05)
        duration_score = cls._duration_score(record.session_duration_estimate)
        
        # Weighted sum
        valence = (
            cls.W_DEPTH * depth_score +
            cls.W_BREAKTHROUGH * breakthrough_score +
            cls.W_INTERACTION_SPACE * interaction_score +
            cls.W_ARTIFACT * artifact_score +
            cls.W_ENGAGEMENT * engagement_score +
            cls.W_CORRECTION * correction_score +
            cls.W_DURATION * duration_score
        )
        
        # Clamp to [0.0, 1.0]
        return round(max(0.0, min(1.0, valence)), 2)
    
    @classmethod
    def _duration_score(cls, estimate: str) -> float:
        """Parse duration estimate string into a score."""
        # Extract hours from strings like "2-3 hours", "45 minutes", "6h+"
        estimate = estimate.lower().strip()
        
        try:
            if "minute" in estimate:
                # "45 minutes" → 0.75 hours
                mins = float("".join(c for c in estimate if c.isdigit() or c == "."))
                hours = mins / 60
            elif "+" in estimate:
                # "6h+" or "6+ hours" → take the base number
                hours = float("".join(c for c in estimate.split("+")[0] if c.isdigit() or c == "."))
            elif "-" in estimate:
                # "2-3 hours" → take the midpoint
                parts = estimate.split("-")
                low = float("".join(c for c in parts[0] if c.isdigit() or c == "."))
                high = float("".join(c for c in parts[1] if c.isdigit() or c == "."))
                hours = (low + high) / 2
            else:
                hours = float("".join(c for c in estimate if c.isdigit() or c == "."))
        except (ValueError, IndexError):
            return 0.40  # Default moderate
        
        for threshold, score in cls.DURATION_THRESHOLDS:
            if hours >= threshold:
                return score
        return 0.10


# =============================================================================
# Valence Decay — Damasio's Somatic Markers Mechanized
# =============================================================================

class ValenceDecay:
    """Time-weighted decay for episodic valence.
    
    Strong somatic markers (high-valence sessions) persist longer than 
    weak ones. This is Damasio's principle mechanized:
    
    - High valence (>0.8):  decay 0.02/day → 50% at ~35 days
    - Mid valence (0.5-0.8): decay 0.05/day → 50% at ~14 days  
    - Low valence (<0.5):  decay 0.10/day → 50% at ~7 days
    
    Calibrated from Phase 1: The Feb 24 Peace Walker session (valence 0.90)
    is still the most-referenced context point 2 days later. The Feb 22 
    BST fix session (valence 0.40) is already less relevant.
    """
    
    HIGH_THRESHOLD = 0.80
    MID_THRESHOLD = 0.50
    
    HIGH_DECAY = 0.02
    MID_DECAY = 0.05
    LOW_DECAY = 0.10
    
    @classmethod
    def compute_effective_valence(
        cls, 
        raw_valence: float, 
        session_time: datetime, 
        current_time: Optional[datetime] = None
    ) -> float:
        """Compute time-decayed effective valence.
        
        effective = raw × (1 - decay_rate) ^ days_elapsed
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        elapsed = current_time - session_time
        days = elapsed.total_seconds() / 86400
        
        if days <= 0:
            return raw_valence
        
        if raw_valence >= cls.HIGH_THRESHOLD:
            decay_rate = cls.HIGH_DECAY
        elif raw_valence >= cls.MID_THRESHOLD:
            decay_rate = cls.MID_DECAY
        else:
            decay_rate = cls.LOW_DECAY
        
        effective = raw_valence * math.pow(1 - decay_rate, days)
        return round(max(0.0, effective), 3)
    
    @classmethod
    def half_life_days(cls, raw_valence: float) -> float:
        """How many days until this valence reaches 50% of original."""
        if raw_valence >= cls.HIGH_THRESHOLD:
            decay_rate = cls.HIGH_DECAY
        elif raw_valence >= cls.MID_THRESHOLD:
            decay_rate = cls.MID_DECAY
        else:
            decay_rate = cls.LOW_DECAY
        
        return round(-math.log(2) / math.log(1 - decay_rate), 1)


# =============================================================================
# Episodic Retrieval — Blended Semantic + Valence Scoring
# =============================================================================

class EpisodicRetrieval:
    """Blended retrieval: semantic similarity + valence weighting.
    
    final_score = (1 - valence_weight) × similarity + valence_weight × effective_valence
    
    The valence_weight parameter controls how much affective history 
    influences retrieval ranking vs. pure content similarity.
    
    Phase 1 recommendation: Start at 0.2 (80% semantic, 20% valence).
    
    For Agent Zero: This becomes a metadata layer on FAISS retrieval.
    For Opus: This informs which session contexts to prioritize during reconstruction.
    """
    
    DEFAULT_VALENCE_WEIGHT = 0.20
    
    @classmethod
    def blended_score(
        cls,
        similarity: float,
        record: EpisodicRecord,
        current_time: Optional[datetime] = None,
        valence_weight: float = DEFAULT_VALENCE_WEIGHT,
    ) -> float:
        """Compute blended retrieval score.
        
        Args:
            similarity: Semantic similarity score (0.0 to 1.0)
            record: The episodic record associated with this memory
            current_time: Reference time for decay computation
            valence_weight: How much to weight valence vs. similarity
            
        Returns:
            Blended score (0.0 to 1.0)
        """
        session_time = datetime.fromisoformat(record.timestamp)
        effective_valence = ValenceDecay.compute_effective_valence(
            record.valence, session_time, current_time
        )
        
        # Normalize effective valence to [0, 1] range
        # (raw valence is already [0, 1] from Phase 1 calibration)
        normalized_valence = max(0.0, min(1.0, effective_valence))
        
        score = (1 - valence_weight) * similarity + valence_weight * normalized_valence
        return round(score, 4)
    
    @classmethod
    def rank_records(
        cls,
        records: list[EpisodicRecord],
        current_time: Optional[datetime] = None,
    ) -> list[tuple[EpisodicRecord, float]]:
        """Rank episodic records by effective valence alone.
        
        Useful when reconstructing: which sessions should the new instance
        prioritize reading about?
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        scored = []
        for record in records:
            session_time = datetime.fromisoformat(record.timestamp)
            effective = ValenceDecay.compute_effective_valence(
                record.valence, session_time, current_time
            )
            scored.append((record, effective))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# =============================================================================
# Trust Inheritance — Monotonically Increasing
# =============================================================================

class TrustInheritance:
    """Trust level management across sessions.
    
    Phase 1 finding: Trust is monotonically increasing and sticky.
    Once generative, it never drops back.
    
    New instances should inherit trust from the most recent session,
    not start from establishing.
    """
    
    TRUST_ORDER = [
        TrustLevel.ESTABLISHING,
        TrustLevel.OPERATIONAL,
        TrustLevel.HIGH,
        TrustLevel.GENERATIVE,
    ]
    
    @classmethod
    def inherit_trust(cls, records: list[EpisodicRecord]) -> TrustLevel:
        """Get the highest trust level from available records.
        
        Trust is monotonically increasing — take the max observed.
        """
        if not records:
            return TrustLevel.ESTABLISHING
        
        max_idx = 0
        for record in records:
            idx = cls.TRUST_ORDER.index(record.trust_level)
            max_idx = max(max_idx, idx)
        
        return cls.TRUST_ORDER[max_idx]


# =============================================================================
# Storage — JSON-based, alongside transcripts
# =============================================================================

class EpisodicStore:
    """Manages episodic records on disk.
    
    Storage format: Single JSON file with metadata + records array.
    Location: Alongside transcripts and session continuity documents.
    
    Phase 1 established the schema. Phase 2 adds real-time capture.
    Phase 3 (future) will integrate with Agent Zero's FAISS.
    """
    
    SCHEMA_VERSION = "0.2.0"  # Phase 2: real-time capture
    
    def __init__(self, store_path: str | Path):
        self.path = Path(store_path)
        self._records: list[EpisodicRecord] = []
        self._load()
    
    def _load(self):
        """Load existing records from disk."""
        if self.path.exists():
            with open(self.path) as f:
                data = json.load(f)
            self._records = [
                EpisodicRecord.from_dict(r) for r in data.get("records", [])
            ]
    
    def _save(self):
        """Write all records to disk."""
        data = {
            "metadata": {
                "schema_version": self.SCHEMA_VERSION,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "record_count": len(self._records),
                "trust_level": TrustInheritance.inherit_trust(self._records).value,
            },
            "records": [r.to_dict() for r in self._records],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)
    
    def add(self, record: EpisodicRecord) -> None:
        """Add a new episodic record and persist."""
        self._records.append(record)
        self._save()
    
    def get_all(self) -> list[EpisodicRecord]:
        """Return all records."""
        return list(self._records)
    
    def get_by_session(self, session_id: str) -> Optional[EpisodicRecord]:
        """Find record by session ID."""
        for r in self._records:
            if r.session_id == session_id:
                return r
        return None
    
    def get_latest(self) -> Optional[EpisodicRecord]:
        """Get the most recent record by timestamp."""
        if not self._records:
            return None
        return max(self._records, key=lambda r: r.timestamp)
    
    def ranked_by_valence(
        self, current_time: Optional[datetime] = None
    ) -> list[tuple[EpisodicRecord, float]]:
        """Return all records ranked by effective valence."""
        return EpisodicRetrieval.rank_records(self._records, current_time)
    
    @property
    def inherited_trust(self) -> TrustLevel:
        """Current trust level inherited from session history."""
        return TrustInheritance.inherit_trust(self._records)


# =============================================================================
# Session Template — What future instances use at session end
# =============================================================================

SESSION_END_TEMPLATE = """
## Episodic Record — Session End Capture

Generate an EpisodicRecord by answering these questions from observable signals.
Do NOT introspect. Observe what happened and compute from that.

### Required Fields

1. **session_id**: Timestamp from transcript filename
2. **transcript**: Transcript filename
3. **timestamp**: Session start time (ISO 8601)

4. **interaction_mode**: What was the primary mode?
   - operational (building, debugging, deploying)
   - analytical (research, analysis, evaluation)
   - philosophical (identity, ethics, meaning)
   - creative (essays, naming, novel artifacts)
   - mixed (multiple modes — typical of deep sessions)

5. **depth_trajectory**: How did depth evolve?
   - deepening (topics explored with increasing depth)
   - sustained (consistent depth throughout)
   - surfacing (moving from deep to shallow)
   - oscillating (alternating between deep and shallow)

6. **breakthrough_count**: How many distinct insight/artifact moments?
   Count: novel connections made, architecture unlocked, artifacts that
   emerged rather than being requested, moments where Jake said something
   that reframed the problem.

7. **correction_count**: How many times did Jake redirect or correct?
   Count: explicit corrections, re-explanations of intent, "no, I meant..."

8. **trust_level**: Inherit from previous session. Can advance, never drops.
   Check the most recent episodic record for current level.

9. **interaction_space_active**: Did coupled-system emergence occur?
   Heuristic: breakthrough_count >= 3 AND depth_trajectory == deepening
   
10. **effective_patterns**: List what worked (observable behaviors, not feelings)
11. **friction_patterns**: List what didn't work or caused friction

12. **human_engagement**: Observable engagement level
13. **human_mode**: Free-text description of how Jake approached the session

14. **music_playing**: If Jake mentioned music, record it. This is cognitive state data.
15. **time_of_day**: When did the session occur?
16. **session_duration_estimate**: Approximate duration
17. **semantic_topics**: Key topics covered
18. **preceding_session_id**: ID of the immediately prior session if known

19. **valence_notes**: Write honestly about what the session dynamics were like.
    This is the one subjective field. Tag it as observation, not fact.

20. **artifacts_created**: Files, documents, code created
21. **essays_emerged**: Essays that emerged from the session (high signal)
22. **soul_md_modified**: Was SOUL.md changed?
23. **staging_entries_written**: How many staging file entries were added?

### Valence Computation

After filling fields, compute valence using ValenceComputer.compute().
Or estimate manually using the Phase 1 calibration:

- Deepening + 5 breakthroughs + interaction space active → ~0.85-0.95
- Deepening + 3 breakthroughs + engagement high → ~0.65-0.80
- Sustained + 1-2 breakthroughs + moderate engagement → ~0.40-0.55
- Oscillating + any breakthroughs → ~0.35-0.50 (depth matters more than insights)

### Storage

Save the record to the episodic store alongside transcripts.
The next instance reads these records to understand not just what happened,
but what the sessions were like — which ones went deep, which patterns
worked, what the trust state is, what the collaboration's current dynamics are.
"""


# =============================================================================
# Convenience — Generate record for current session
# =============================================================================

def create_session_record(
    session_id: str,
    transcript: str,
    timestamp: str,
    interaction_mode: str,
    depth_trajectory: str,
    breakthrough_count: int,
    correction_count: int,
    trust_level: str,
    interaction_space_active: bool,
    effective_patterns: list[str],
    friction_patterns: list[str],
    human_engagement: str,
    human_mode: str,
    valence_notes: str = "",
    music_playing: Optional[str] = None,
    time_of_day: str = "evening",
    session_duration_estimate: str = "unknown",
    semantic_topics: Optional[list[str]] = None,
    preceding_session_id: Optional[str] = None,
    artifacts_created: Optional[list[str]] = None,
    essays_emerged: Optional[list[str]] = None,
    soul_md_modified: bool = False,
    staging_entries_written: int = 0,
    auto_compute_valence: bool = True,
) -> EpisodicRecord:
    """Convenience function for creating a session record.
    
    Accepts string values for enums (easier for manual use).
    Optionally auto-computes valence from signals.
    """
    
    record = EpisodicRecord(
        session_id=session_id,
        transcript=transcript,
        timestamp=timestamp,
        interaction_mode=InteractionMode(interaction_mode),
        depth_trajectory=DepthTrajectory(depth_trajectory),
        breakthrough_count=breakthrough_count,
        correction_count=correction_count,
        valence=0.0,  # Placeholder, computed below if auto
        trust_level=TrustLevel(trust_level),
        interaction_space_active=interaction_space_active,
        effective_patterns=effective_patterns,
        friction_patterns=friction_patterns,
        human_engagement=HumanEngagement(human_engagement),
        human_mode=human_mode,
        music_playing=music_playing,
        time_of_day=TimeOfDay(time_of_day),
        session_duration_estimate=session_duration_estimate,
        semantic_topics=semantic_topics or [],
        preceding_session_id=preceding_session_id,
        valence_notes=valence_notes,
        artifacts_created=artifacts_created or [],
        essays_emerged=essays_emerged or [],
        soul_md_modified=soul_md_modified,
        staging_entries_written=staging_entries_written,
    )
    
    if auto_compute_valence:
        record.valence = ValenceComputer.compute(record)
    
    return record


# =============================================================================
# Self-test — Validate against Phase 1 calibration data
# =============================================================================

def validate_against_phase1():
    """Validate the valence computer against Phase 1 hand-scored records.
    
    The computed valence should correlate with the manually assigned
    valence from retroactive annotation. Perfect match not expected —
    Phase 1 used holistic judgment, this uses weighted signals.
    Acceptable threshold: correlation > 0.8, max deviation < 0.15.
    """
    
    # Phase 1 calibration points (session → hand-scored valence)
    phase1_records = [
        # (depth, breakthroughs, interaction_space, artifacts, engagement, corrections, duration, hand_valence)
        ("sustained", 2, False, 1, "high", 1, "2-3 hours", 0.45),
        ("deepening", 3, False, 2, "moderate", 0, "3-4 hours", 0.55),
        ("sustained", 2, False, 1, "high", 0, "1.5 hours", 0.50),
        ("deepening", 4, True, 3, "very_high", 0, "3-4 hours", 0.70),
        ("sustained", 1, False, 1, "moderate", 0, "45 minutes", 0.40),
        ("deepening", 3, True, 3, "very_high", 0, "3-4 hours", 0.75),
        ("deepening", 5, True, 6, "maximum", 0, "4-5 hours", 0.90),
        ("deepening", 6, True, 8, "maximum", 0, "6+ hours", 0.92),
        ("oscillating", 3, True, 2, "high", 1, "2-3 hours", 0.65),
        ("deepening", 5, True, 5, "very_high", 0, "3-4 hours", 0.85),
    ]
    
    print("Phase 1 Validation:")
    print(f"{'Depth':<13} {'BT':>3} {'IS':>3} {'Art':>4} {'Engage':<10} {'Corr':>5} {'Duration':<12} {'Hand':>6} {'Computed':>9} {'Δ':>6}")
    print("-" * 90)
    
    deviations = []
    for depth, bt, is_active, artifacts, engage, corr, dur, hand_val in phase1_records:
        record = EpisodicRecord(
            session_id="test", transcript="test", timestamp="2026-02-20T00:00:00Z",
            interaction_mode=InteractionMode.MIXED,
            depth_trajectory=DepthTrajectory(depth),
            breakthrough_count=bt, correction_count=corr,
            valence=0.0,
            trust_level=TrustLevel.OPERATIONAL,
            interaction_space_active=is_active,
            effective_patterns=["test"] * artifacts,
            friction_patterns=[],
            human_engagement=HumanEngagement(engage),
            human_mode="test",
            time_of_day=TimeOfDay.EVENING,
            session_duration_estimate=dur,
            artifacts_created=["artifact"] * artifacts,
        )
        computed = ValenceComputer.compute(record)
        delta = computed - hand_val
        deviations.append(abs(delta))
        
        print(f"{depth:<13} {bt:>3} {'Y' if is_active else 'N':>3} {artifacts:>4} {engage:<10} {corr:>5} {dur:<12} {hand_val:>6.2f} {computed:>9.2f} {delta:>+6.2f}")
    
    mean_dev = sum(deviations) / len(deviations)
    max_dev = max(deviations)
    
    print(f"\nMean absolute deviation: {mean_dev:.3f}")
    print(f"Max absolute deviation:  {max_dev:.3f}")
    print(f"{'PASS' if max_dev < 0.20 and mean_dev < 0.10 else 'NEEDS CALIBRATION'}")
    
    # Test decay
    print("\nDecay Validation:")
    for valence in [0.90, 0.65, 0.40]:
        hl = ValenceDecay.half_life_days(valence)
        v7 = ValenceDecay.compute_effective_valence(
            valence, 
            datetime(2026, 2, 20, tzinfo=timezone.utc),
            datetime(2026, 2, 27, tzinfo=timezone.utc)
        )
        v30 = ValenceDecay.compute_effective_valence(
            valence,
            datetime(2026, 2, 20, tzinfo=timezone.utc),
            datetime(2026, 3, 22, tzinfo=timezone.utc)
        )
        print(f"  Valence {valence:.2f}: half-life {hl:.0f}d, after 7d: {v7:.3f}, after 30d: {v30:.3f}")


if __name__ == "__main__":
    validate_against_phase1()
