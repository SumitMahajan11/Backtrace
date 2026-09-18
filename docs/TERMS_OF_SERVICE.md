# Terms of Service

**Last Updated:** September 17, 2026  
**Status:** Draft for Legal Counsel Review (Not Formal Legal Advice)

---

### IMPORTANT LEGAL NOTICE
> [!IMPORTANT]
> This document is a technical and operational draft of the Terms of Service for **Backtrace** ("the Service"), reflecting the actual capabilities, constraints, and data flows of the software codebase. This draft must be reviewed, adjusted, and approved by qualified legal counsel before production publication, particularly regarding applicable regional regulations and jurisdiction-specific dispute resolution.

---

### 1. Acceptance of Terms
By authenticating via GitHub OAuth, accessing, or using Backtrace, you ("User" or "You") agree to be bound by these Terms of Service. If you do not agree to these Terms, you must not access or use the Service.

### 2. Description of the Service
Backtrace provides an automated codebase reverse-engineering and architecture narration platform. The Service analyzes software repository structures, dependency graphs, git commit histories, and code syntax to generate structural walkthroughs, dependency tiers, and build-sequence explanations.

### 3. Account Registration & Authentication
- Authentication is handled via **GitHub OAuth 2.0**. You are responsible for maintaining the security of your GitHub account credentials.
- You must provide authorized access to repositories you submit for analysis.
- Backtrace issues JSON Web Tokens (JWT) for API session management, stored in secure HTTP-only session cookies. You agree not to attempt to forge, reverse-engineer, or tamper with JWT claims or session state.

### 4. Acceptable Use Policy
You agree not to use Backtrace to:
1. Submit repositories containing malicious code, viruses, trojans, ransomware, or exploits designed to compromise or disrupt computer systems.
2. Attempt to bypass sandbox execution boundaries, file system locks, or resource caps (e.g., zip bombs, recursive directory traversal).
3. Circumvent monthly analysis quotas, rate limiting headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`), or billing restrictions.
4. Scan or analyze proprietary third-party repositories without authorization from the copyright holder.

### 5. Repository Submissions & Intellectual Property
- **Your Code Remains Yours:** You retain all copyright, ownership, and intellectual property rights in and to any source code, repository metadata, or proprietary algorithms submitted to Backtrace.
- **License to Analyze:** By submitting a repository, you grant Backtrace a limited, revocable, non-exclusive license to ingest, parse, segment, and index the code strictly for the purpose of generating analysis results, architectural diagrams, and narration reports for your account.
- **Generated Analysis Output:** Analysis results, dependency graphs, and narration reports generated for your submitted repositories are provided for your educational, engineering, and commercial development use.

### 6. Subscriptions, Billing & Quotas
- **Free Tier:** Users on the Free Tier receive a bounded quota (default: 5 repository analyses per month) for public repositories up to established file-size caps.
- **Pro Tier:** Paid subscriptions are billed on a recurring monthly or annual basis via **Stripe**.
- **Payment Processing:** All payment transactions, credit card data handling, and invoice generations are processed by Stripe, Inc. Backtrace does not store raw credit card numbers or CVV codes.
- **Cancellation & Downgrades:** You may cancel your subscription at any time via your account settings. Upon cancellation, your subscription remains active until the end of the current billing period, after which your account reverts to Free Tier limits.

### 7. Service Availability & Processing Locks
- Backtrace processes repository analyses through an in-process orchestration pipeline protected by transient concurrency locks.
- While the Service strives for high availability, Backtrace does not guarantee uninterrupted operation or zero latency during intensive AST parsing or git graph extraction.
- In the event of a processing crash or timeout (15-minute lock threshold), incomplete analyses are automatically marked as failed, releasing the concurrency lock.

### 8. Disclaimer of Warranties
THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED. BACKTRACE DOES NOT GUARANTEE THAT RECONSTRUCTED BUILD SEQUENCES, ARCHITECTURAL CLASSIFICATIONS, OR CODE EXPLANATIONS ARE 100% ERROR-FREE OR IMMUNE TO REPOSITORY HISTORICAL AMBIGUITIES. USERS MUST INDEPENDENTLY VERIFY SYSTEM ARCHITECTURES BEFORE MAKING CRITICAL PRODUCTION ENGINEERING DECISIONS.

### 9. Limitation of Liability
TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL BACKTRACE, ITS CREATORS, OR CONTRIBUTORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, OR BUSINESS INTERRUPTION, ARISING OUT OF OR IN CONNECTION WITH YOUR USE OF THE SERVICE.

### 10. Modifications to Terms
We reserve the right to modify these Terms at any time. Continued use of the Service after any such changes constitutes your acceptance of the new Terms of Service.
