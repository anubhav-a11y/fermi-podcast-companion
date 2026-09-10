"""Build a tiny synthetic corpus so the pipeline can be tested with no audio,
no API keys and no spend.

    python scripts/make_fixture.py     # writes artifacts_fixture/

This exists so you can prove the plumbing works (chunk -> index -> route ->
retrieve -> answer -> judge) in about five seconds, before committing an
hour to transcription. It is NOT a substitute for the real run: the fixture
text is invented, and the eval numbers you report must come from the real
audio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "artifacts_fixture"

EPISODES = [
    ("Condensed Matter And Emergence", [
        "Welcome back. Today we are talking about condensed matter physics, which is really the physics of many particles acting together.",
        "The slogan people use is more is different. Phil Anderson wrote that in nineteen seventy two and it has shaped the field ever since.",
        "What he meant is that when you put an enormous number of particles together, the collective behaviour obeys its own laws.",
        "You cannot derive superconductivity from a single electron. The property is emergent. It belongs to the collective, not to the parts.",
        "So reductionism is true but not useful here. Knowing the fundamental equation does not tell you what a crystal will do.",
        "Let me give a concrete example. Take a single water molecule. There is no temperature at which it is wet, and there is no freezing point for one molecule.",
        "Wetness and freezing are properties of the ensemble. That is emergence in one sentence.",
        "Superconductivity is the dramatic case. Below a critical temperature the resistance drops to exactly zero, not approximately zero.",
        "Bardeen, Cooper and Schrieffer explained it in nineteen fifty seven. Electrons pair up through the lattice and the pairs condense.",
        "The pairing is counterintuitive because two electrons repel. The lattice mediates an effective attraction.",
        "The high temperature cuprates from nineteen eighty six still do not have an agreed mechanism. That remains genuinely open.",
        "I would say that is the biggest unsolved problem in the field, and honest people disagree about it.",
        "Noise in these systems is thermal. Heat the sample and the collective order melts away.",
        "The experimental side matters enormously here. Theory has repeatedly followed the materials rather than led them.",
    ]),
    ("Quantum Computing And Decoherence", [
        "This episode is about quantum computing, and specifically about why it is so hard to build a machine that works.",
        "A qubit can be in a superposition of zero and one, and that is the source of the advantage.",
        "But superposition is fragile. The moment the qubit interacts with its environment, the phase information leaks out.",
        "That leaking is decoherence. It is not a mistake in the calculation, it is the environment measuring your qubit for you.",
        "Coherence times in good superconducting transmon devices are now in the hundreds of microseconds.",
        "That sounds short, and it is, but gate times are tens of nanoseconds, so you get thousands of operations.",
        "The reason a quantum error is harder than a classical one is that you cannot copy the state to check it.",
        "The no cloning theorem forbids it. So error correction has to measure something other than the state itself.",
        "The surface code measures parity between neighbouring qubits. The parity tells you an error happened without telling you the state.",
        "The cost is brutal. You might need a thousand physical qubits for one reliable logical qubit.",
        "Noise here is the central engineering problem. Every noise source, thermal, magnetic, cosmic rays, has to be suppressed.",
        "And unlike condensed matter, you cannot just cool your way out of it. Some noise is intrinsic to control electronics.",
        "We are in what people call the NISQ era. Noisy, intermediate scale, and honestly still looking for a killer application.",
        "I am optimistic on a twenty year horizon and quite sceptical about most five year claims you read.",
    ]),
    ("Astrophysics At Extreme Density", [
        "Today, neutron stars. An object with the mass of the sun compressed into something the size of a city.",
        "The density is around ten to the seventeen kilograms per cubic metre. A sugar cube of that stuff weighs as much as a mountain.",
        "What holds it up is neutron degeneracy pressure, which is quantum mechanical, not thermal.",
        "So this is condensed matter physics in a regime no laboratory can ever reach.",
        "The interior may be a superfluid, and possibly a superconductor. The same pairing physics turns up again.",
        "The main observational challenge is that we cannot see inside. Everything we know comes from the surface and the orbit.",
        "Pulsar timing is our best probe. The rotation is a clock accurate to better than a microsecond.",
        "Glitches in that timing are thought to be the superfluid interior slipping relative to the crust.",
        "Gravitational waves changed the game in twenty seventeen when LIGO caught two neutron stars merging.",
        "That single event constrained the equation of state better than decades of previous work.",
        "The equation of state is the open question. How stiff is matter at that density? We still do not know.",
        "Noise is our permanent enemy observationally. Detector noise, and the interstellar medium smearing the signal.",
        "Theory is far ahead of observation here, which is the opposite of the condensed matter story.",
    ]),
]


def build() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    episodes = []
    for i, (title, lines) in enumerate(EPISODES, start=1):
        segs, t = [], 12.0
        for line in lines:
            dur = 3.0 + 0.36 * len(line.split())
            segs.append({"start": round(t, 2), "end": round(t + dur, 2), "text": line})
            t += dur + 0.6
        episodes.append({
            "episode_id": f"E{i}", "title": title,
            "audio_path": str(ROOT / "data" / "audio" / f"fixture_{i}.mp3"),
            "duration_s": round(t, 2), "asr_provider": "fixture",
            "asr_model": "fixture", "segments": segs,
        })

    (FIXTURE_DIR / "transcripts.json").write_text(
        json.dumps({"episodes": episodes}, indent=2))

    # Episode cards, handwritten to match the fixture text.
    cards = [
        {"episode_id": "E1", "file_title": episodes[0]["title"],
         "title": "Condensed Matter and Emergence",
         "summary": "Why collections of particles obey laws their parts do not. Covers "
                    "Anderson's 'more is different', emergence, and BCS superconductivity. "
                    "Suits a learner new to condensed matter.",
         "topics": ["emergence", "more is different", "superconductivity", "BCS theory",
                    "Cooper pairs", "cuprates", "reductionism", "phase transitions",
                    "thermal noise"],
         "outline": [{"start_s": 12, "label": "What condensed matter is"},
                     {"start_s": 60, "label": "More is different"},
                     {"start_s": 200, "label": "Superconductivity and BCS"}],
         "duration_s": episodes[0]["duration_s"], "audio_path": episodes[0]["audio_path"],
         "asr_model": "fixture"},
        {"episode_id": "E2", "file_title": episodes[1]["title"],
         "title": "Quantum Computing and Decoherence",
         "summary": "Why quantum computers are hard to build. Covers qubits, superposition, "
                    "decoherence, no-cloning, the surface code, and the NISQ era. Suits a "
                    "learner who knows what a qubit is.",
         "topics": ["qubits", "superposition", "decoherence", "coherence time", "transmon",
                    "no-cloning theorem", "quantum error correction", "surface code",
                    "NISQ", "noise"],
         "outline": [{"start_s": 12, "label": "Qubits and superposition"},
                     {"start_s": 120, "label": "Decoherence"},
                     {"start_s": 260, "label": "Error correction"}],
         "duration_s": episodes[1]["duration_s"], "audio_path": episodes[1]["audio_path"],
         "asr_model": "fixture"},
        {"episode_id": "E3", "file_title": episodes[2]["title"],
         "title": "Astrophysics at Extreme Density",
         "summary": "Neutron stars as physics laboratories no lab can build. Covers degeneracy "
                    "pressure, superfluid interiors, pulsar timing, and the 2017 LIGO merger. "
                    "Suits a learner interested in observational astrophysics.",
         "topics": ["neutron stars", "degeneracy pressure", "superfluidity", "pulsar timing",
                    "glitches", "gravitational waves", "LIGO", "equation of state",
                    "detector noise"],
         "outline": [{"start_s": 12, "label": "What a neutron star is"},
                     {"start_s": 140, "label": "Observational probes"},
                     {"start_s": 240, "label": "Open questions"}],
         "duration_s": episodes[2]["duration_s"], "audio_path": episodes[2]["audio_path"],
         "asr_model": "fixture"},
    ]
    (FIXTURE_DIR / "episodes.json").write_text(json.dumps({"episodes": cards}, indent=2))
    print(f"Wrote fixture transcripts + episode cards to {FIXTURE_DIR}")
    print("Next:  make smoke")


if __name__ == "__main__":
    build()
