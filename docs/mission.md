# Interview Evidence Auditor
## Mission and scope

### The two parts of the product

The product has two complementary outputs:

1. **The evidence audit:** the checked assessment described below, with claim-level results, concern types, explanations, and supporting, contradicting, or qualifying interview excerpts.

2. **A basic visual review tool:** an interactive view connecting the audit to the original assessment and interview. When the reviewer selects a finding, the tool highlights the relevant claim in the assessment and its associated evidence in the interview. Highlights distinguish supporting, contradicting, and qualifying evidence.

The audit explains the potential discrepancy. The visual tool makes it easy to inspect that discrepancy in context. Both support human review without automatically changing the assessment.

### Our mission

We are building a tool that checks whether a written assessment faithfully represents the evidence in an interview.

The user provides an interview and the assessment, explanation, or recommendation produced from it. The tool examines the factual claims in that assessment, identifies potential discrepancies, and shows the relevant interview evidence for human review.

**The central question is: Does the supplied interview substantiate what the assessor claims happened, was said, or was reported?**

The starting use case is a clinician explaining an assessment. The same approach can apply to hiring interviews, research interviews, investigations, and other situations where someone uses an interview to support a decision.

### The problem

A written assessment can sound convincing while changing the meaning of its source evidence.

A statement may be attributed to the wrong person. An occasional experience may become a frequent pattern. Something that happened years ago may become a current problem. A tentative answer may become a definite fact. A qualification, correction, or conflicting account may disappear.

These discrepancies are not always obvious when reading the assessment alone. Checking them requires returning to the interview, locating the relevant passages, and understanding their context.

We want to make that review easier by connecting assessment claims to supporting, contradicting, and qualifying evidence.

The intended benefit is more faithful documentation and more focused human review. This build explores that benefit; it does not establish it.

### What we are building

The product produces an **evidence-consistency audit** of an assessment.

It should help a reviewer understand:

- Which factual claims are supported by the interview.
- Which claims conflict with the interview.
- Which claims preserve some evidence but change its meaning.
- Which claims cannot be substantiated from the supplied material.
- Which passages need to be inspected before deciding whether a correction is warranted.

The tool identifies **potential concerns**. A human reviewer determines whether those concerns are valid and what action to take.

### Domain and input independence

The core checks concern language, attribution, context, and evidence. They do not depend on a particular diagnosis, rating scale, interview protocol, or industry.

The same checks should work when the assessment concerns a clinical interview, a job candidate, or a research participant. This is a design goal, not a claim that performance will be identical across domains or languages.

The idea is also independent of the original source format. The interview might originate from a recording, transcript, or document. The audit operates on the interview content made available to it.

**The essential inputs are readable interview content and the assessor’s written response.** Supporting every recording or file format is separate from the mission.

## What the tool checks

The following twelve checks define the scope of this build. The examples are illustrative.

| Check | What it checks | Example potential discrepancy |
|---|---|---|
| **1. Claim support** | Whether a factual assertion is substantiated by the supplied interview. | The assessment says the person repeatedly missed appointments, but the interview establishes only one missed appointment. |
| **2. Contradictory evidence** | Whether explicit interview evidence conflicts with an assessment claim. | The person denies difficulty managing finances, but the assessment says they reported that difficulty. |
| **3. Wrong person or source attribution** | Who experienced something, who reported it, and whether those sources are represented correctly. | A parent describes their own forgetfulness, but the assessment attributes it to the participant. |
| **4. Timeframe mismatch** | Whether past, current, future, and hypothetical statements retain their original timing. | Childhood difficulty is presented as a current problem. |
| **5. Negation reversal** | Whether a denial, absence, or exception becomes an affirmative statement, or the reverse. | “I don’t lose my keys” becomes a claim that the person frequently loses their keys. |
| **6. Certainty inflation** | Whether tentative statements, estimates, or secondhand information become definite facts. | “I think this happened twice” becomes a confirmed, consistent pattern. |
| **7. Frequency or severity inflation** | Whether the assessment exaggerates frequency, duration, intensity, or impact. | Occasional difficulty becomes daily difficulty, or inconvenience becomes inability. |
| **8. Context stripping** | Whether an omitted qualification materially changes the meaning of a claim. | Difficulty occurring only after several nights without sleep becomes an unrestricted claim about everyday functioning. |
| **9. Question mistaken for an answer** | Whether the interviewer’s question, suggestion, or hypothetical is treated as respondent evidence. | “Do you often forget things?” is used as proof without an affirmative response. |
| **10. Correction ignored** | Whether later clarification or retraction changes an earlier statement used in the assessment. | The person corrects “every week” to “twice last year,” but the original frequency remains in the assessment. |
| **11. Conflicting accounts flattened** | Whether unresolved disagreement between sources is presented as agreement. | Participant and caregiver disagree, but the assessment says both describe the same experience. |
| **12. Unsupported causal links** | Whether the assessment presents a cause-and-effect relationship as established by the interview when the source does not substantiate it. | Two events occurred around the same time; the assessment says the interview establishes that one caused the other. |

### How these checks should be interpreted

**Faithful paraphrases are acceptable.** The assessment does not need to repeat the interview word for word. The question is whether it preserves the meaning.

**Missing evidence is different from contradictory evidence.** If the interview does not establish a claim, that does not automatically mean the claim is false.

**Context matters.** A short answer such as “yes” can support a claim when interpreted alongside the preceding question. An interviewer’s question alone cannot.

**Later statements require interpretation.** A clear correction can supersede an earlier statement. An unresolved disagreement should remain unresolved rather than automatically favoring the latest statement.

**Not every omission is a concern.** An assessment can summarize selectively. An omission matters here when it changes the meaning of a claim that the assessment does make.

**Reported explanations and assessor inferences are different.** “The participant believes X caused Y” is different from “X caused Y.” The tool should preserve that distinction.

## What the reviewer receives

Each finding should contain:

- **The assessment claim** being checked.
- **Relevant interview excerpts**, including support and counterevidence where available.
- **The concern type**, such as timeframe mismatch or context stripping.
- **A concise explanation** of the possible discrepancy.
- **A source location** that lets the reviewer inspect the original context.

Timestamps may be used when supplied. Otherwise, another reliable source location is sufficient. The tool must never invent quotations, speaker identities, or timestamps.

The audit should distinguish:

| Result | Meaning |
|---|---|
| **Supported** | The supplied interview substantiates the claim without a material change in meaning. |
| **Contradicted** | Explicit supplied evidence conflicts with the claim. |
| **Partially supported** | Some elements are supported, but others are exaggerated, altered, or unsubstantiated. |
| **Insufficient evidence** | The available material does not establish the claim, or ambiguity prevents a reliable assessment. |

Claims requiring external criteria or unavailable observations should be identified as **outside the audit’s scope**, rather than forced into a factual verdict.

A claim can have multiple concerns. The report should explain the underlying discrepancy without overwhelming the reviewer with repetitive findings.

## Our boundaries

### Evidence consistency rather than real-world truth

The tool checks fidelity to the supplied interview. It does not independently verify whether the participant’s statements are true.

The clinician or assessor may also have information that was not supplied. The appropriate wording is:

> “This claim is not substantiated by the supplied interview.”

That is different from alleging fabrication, dishonesty, or professional misconduct.

### Factual premises rather than clinical correctness

The tool does not diagnose, assign scores, audit scoring rules, or decide whether a final clinical conclusion is correct.

For example, if a clinician explains a diagnosis using three reported behaviors, the tool can check whether the interview supports those behaviors. It does not determine whether those behaviors satisfy diagnostic criteria.

A clinical conclusion can be a legitimate inference without being directly spoken by the participant.

### No interview administration or protocol review

This build does not check:

- Required questions or probes.
- Interview completeness or interviewing skill.
- Consent procedures.
- Administrative fields.
- Protocol compliance.
- Numerical score calculations.
- Specialty-specific diagnostic or rating criteria.

Those are separate builds and should not expand today’s scope.

### Supplied evidence defines the limit

The tool cannot confidently resolve unclear speaker identity, missing source material, transcription errors, or findings that depend on visual observations unavailable to it.

These limitations should produce a narrower finding or an insufficient-evidence result.

**No detected concerns does not mean the assessment is correct.** It means this audit did not identify a concern in the supplied material.

## Principles

1. **Make concerns traceable.** Every finding should connect to an identifiable assessment claim and inspectable source evidence.
2. **Look for counterevidence.** A supporting excerpt is insufficient if nearby or later passages materially qualify it.
3. **Preserve uncertainty.** Do not turn ambiguous evidence into a confident accusation.
4. **Accept legitimate summarization.** Check meaning, not wording.
5. **Separate facts from inference.** Audit factual premises without pretending to validate every conclusion.
6. **Keep human judgment central.** Findings are proposals to review, not automatic corrections.
7. **Keep the build narrow.** The mission is evidence consistency across domains.
