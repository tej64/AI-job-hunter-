import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("job-agent")
RESULTS_FILE = Path(__file__).with_name("job_results.jsonl")


class ResumeMatcher:
    STOP_WORDS = {
        "the", "and", "for", "with", "that", "this", "from", "have", "your", "into", "will", "about",
        "been", "more", "than", "also", "their", "there", "over", "under", "after", "before", "using",
        "work", "working", "job", "jobs", "resume", "candidate", "team", "role", "skills", "experience",
        "present", "support", "provides", "strong", "clear", "full", "day", "years", "year", "hands"
    }

    HIGH_VALUE_KEYWORDS = {
        "site reliability engineer",
        "sre",
        "reliability",
        "incident",
        "incident response",
        "observability",
        "monitoring",
        "alert",
        "root cause",
        "production",
        "oncall",
        "on-call",
        "kubernetes",
        "terraform",
        "aws",
        "cloud",
        "docker",
        "devops",
        "automation",
        "python",
        "bash",
        "slo",
        "error budget",
        "runbook",
        "reliability engineer",
        "system reliability",
    }

    def __init__(self, resume_path: str):
        self.resume_path = resume_path
        self.resume_text = self._load_resume_text()
        self.resume_keywords = self.extract_keywords(self.resume_text)
        self.resume_signals = self.extract_resume_signals(self.resume_text)

    def _load_resume_text(self) -> str:
        if not self.resume_path or not Path(self.resume_path).exists():
            logger.warning("Resume file '%s' was not found. Resume matching will be skipped.", self.resume_path)
            return ""

        try:
            with open(self.resume_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                return file_obj.read()
        except Exception as exc:
            logger.warning("Could not read resume file '%s': %s", self.resume_path, exc)
            return ""

    def extract_keywords(self, text: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        return {token for token in tokens if len(token) > 2 and token not in self.STOP_WORDS}

    def extract_resume_signals(self, text: str) -> set[str]:
        normalized = re.sub(r"\s+", " ", text.lower())
        signals = set()
        for phrase in self.HIGH_VALUE_KEYWORDS:
            if phrase in normalized:
                signals.add(phrase)
        return signals

    def score_job(self, title: str, body_text: str, profile_context: str = "") -> tuple[bool, float, list[str]]:
        if not self.resume_keywords:
            return True, 1.0, []

        title_text = (title or "").lower()
        body_text = (body_text or "").lower()
        profile_context = (profile_context or "").lower()
        title_keywords = self.extract_keywords(title_text)
        body_keywords = self.extract_keywords(body_text)
        profile_keywords = self.extract_keywords(profile_context)

        overlap = sorted(self.resume_keywords.intersection(title_keywords.union(body_keywords, profile_keywords)))
        overlap_score = len(overlap)

        if overlap_score == 0:
            return False, 0.0, []

        threshold = int(os.getenv("MATCH_THRESHOLD", "5"))

        title_bonus = len(title_keywords.intersection(self.resume_keywords)) * 2
        signal_bonus = 0
        for signal in self.resume_signals:
            if signal in title_text or signal in body_text or signal in profile_context:
                signal_bonus += 2

        profile_bonus = len(profile_keywords.intersection(self.resume_keywords)) * 3
        semantic_bonus = 0
        for phrase in ["site reliability engineer", "reliability engineer", "site reliability", "sre"]:
            if phrase in title_text and phrase in self.resume_text.lower():
                semantic_bonus += 3

        score = overlap_score + title_bonus + signal_bonus + profile_bonus + semantic_bonus
        matched = score >= threshold
        return matched, float(score), overlap


class BrowserAutomation:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.user_agent = os.getenv("PORTAL_USER_AGENT", "Mozilla/5.0")
        self.linkedin_profile_url = os.getenv("LINKEDIN_PROFILE_URL", "").strip()

    def read_job_page(self, job_url: str) -> str:
        with sync_playwright() as playwright_module:
            browser = playwright_module.chromium.launch(headless=self.headless)
            page = browser.new_page(user_agent=self.user_agent)
            try:
                page.goto(job_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                return page.locator("body").inner_text(timeout=30000)
            finally:
                browser.close()

    def read_profile_page(self, profile_url: str) -> str:
        if not profile_url:
            return ""

        with sync_playwright() as playwright_module:
            browser = playwright_module.chromium.launch(headless=self.headless)
            page = browser.new_page(user_agent=self.user_agent)
            try:
                page.goto(profile_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                return page.locator("body").inner_text(timeout=30000)
            finally:
                browser.close()

    def build_search_url(self, portal: str, keywords: list[str]) -> str:
        query = quote(" ".join(keywords))
        if portal == "linkedin":
            return f"https://www.linkedin.com/jobs/search/?keywords={query}&location=India"
        if portal == "indeed":
            return f"https://in.indeed.com/jobs?q={query}&l=India"
        return f"https://www.google.com/search?q={quote('site:' + portal + ' ' + ' '.join(keywords))}"

    def scrape_jobs(self, portal: str, keywords: list[str]) -> list[dict[str, str]]:
        search_url = self.build_search_url(portal, keywords)
        jobs: list[dict[str, str]] = []

        with sync_playwright() as playwright_module:
            browser = playwright_module.chromium.launch(headless=self.headless)
            page = browser.new_page(user_agent=self.user_agent)
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)

                selectors = {
                    "linkedin": "a[href*='/jobs/']",
                    "indeed": "a[href*='/jobs/']",
                }

                raw_jobs = page.locator(selectors.get(portal, "a[href]")).evaluate_all(
                    "(elements) => elements.map((el) => ({ text: (el.innerText || '').trim(), href: (el.href || '').trim() }))"
                )

                for item in raw_jobs[:5]:
                    title = item.get("text") or ""
                    href = item.get("href") or ""
                    if title and href and "javascript:" not in href.lower():
                        jobs.append({"portal": portal, "title": title, "url": href})
            finally:
                browser.close()

        return jobs

    def _login_to_linkedin(self, page) -> None:
        username = os.getenv("PORTAL_USERNAME", "").strip()
        password = os.getenv("PORTAL_PASSWORD", "").strip()

        placeholder_markers = {
            "your_linkedin_email@example.com",
            "your_linkedin_password",
            "your-profile",
            "your_linkedin",
            "example.com",
        }

        if not username or not password:
            logger.info("No LinkedIn credentials configured; continuing with public profile browsing session.")
            return

        if any(marker in username.lower() or marker in password.lower() for marker in placeholder_markers):
            logger.warning(
                "LinkedIn credentials in .env still use placeholder/example values. Update .env with real credentials to enable profile-aware login."
            )
            return

        logger.info("Using LinkedIn credentials from environment for profile-aware application flow.")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2000)

        for selector in [
            "input[type='email']",
            "input[name='session_key']",
            "input[name='username']",
        ]:
            if page.locator(selector).count() > 0:
                page.locator(selector).first.fill(username)
                break

        for selector in [
            "input[type='password']",
            "input[name='password']",
        ]:
            if page.locator(selector).count() > 0:
                page.locator(selector).first.fill(password)
                break

        submit_button = page.locator("button[type='submit'], input[type='submit']").first
        if submit_button.count() > 0:
            submit_button.click()
            page.wait_for_timeout(3000)

        if self.linkedin_profile_url:
            page.goto(self.linkedin_profile_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2000)

    def _dismiss_modal_overlays(self, page) -> None:
        dismissal_selectors = [
            "button:has-text('Dismiss')",
            "button:has-text('Close')",
            "button[aria-label='Dismiss']",
            "button[aria-label='Close']",
        ]

        for selector in dismissal_selectors:
            try:
                candidate = page.locator(selector)
                if candidate.count() > 0 and candidate.first.is_visible(timeout=1000):
                    candidate.first.click(timeout=5000, force=True)
                    page.wait_for_timeout(1000)
            except Exception:
                continue

        try:
            page.evaluate(
                """
                () => {
                    document.querySelectorAll('.modal__overlay, .top-level-modal-container, .contextual-sign-in-modal__right-content').forEach(el => {
                        el.style.pointerEvents = 'none';
                        el.style.display = 'none';
                    });
                }
                """
            )
        except Exception:
            pass

    def attempt_apply(self, job: dict[str, str]) -> bool:
        with sync_playwright() as playwright_module:
            browser = playwright_module.chromium.launch(headless=self.headless)
            page = browser.new_page(user_agent=self.user_agent)
            try:
                if job.get("portal", "").lower() == "linkedin":
                    self._login_to_linkedin(page)

                page.goto(job["url"], wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                self._dismiss_modal_overlays(page)

                clickable_selectors = [
                    "button:has-text('Apply')",
                    "a:has-text('Apply')",
                    "button:has-text('Quick apply')",
                    "a:has-text('Quick apply')",
                ]

                for selector in clickable_selectors:
                    candidate = page.locator(selector)
                    if candidate.count() == 0:
                        continue

                    try:
                        if candidate.first.is_visible(timeout=3000):
                            candidate.first.click(timeout=10000, force=True)
                            page.wait_for_timeout(2000)
                            logger.info("Application step initiated for %s using LinkedIn profile-aware flow.", job["title"])
                            return True
                    except Exception as click_exc:
                        logger.warning("Selector %s was present but not clickable for %s: %s", selector, job["title"], click_exc)
                        continue

                logger.info("No direct apply control found for %s; page inspected successfully.", job["title"])
                return False
            except Exception as exc:
                logger.warning("Application attempt for %s failed gracefully: %s", job["title"], exc)
                return False
            finally:
                browser.close()


class JobAgent:
    def __init__(self):
        self.portals = [portal.strip() for portal in os.getenv("JOB_PORTALS", "linkedin,indeed").split(",") if portal.strip()]
        self.keywords = [
            keyword.strip()
            for keyword in os.getenv("JOB_KEYWORDS", "site reliability engineer,devops,aws,kubernetes,observability,automation").split(",")
            if keyword.strip()
        ]
        self.browser = BrowserAutomation(headless=os.getenv("BROWSER_HEADLESS", "true").lower() == "true")
        self.resume_matcher = ResumeMatcher(os.getenv("RESUME_PATH", "resume.txt"))

    def extract_company_name(self, title: str, page_text: str, job_url: str = "") -> str:
        def clean_company_candidate(value: str) -> str:
            cleaned = re.sub(r"\s+", " ", value or "").strip(" \t\n\r-|")
            cleaned = re.sub(r"^at\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s+is hiring$", "", cleaned, flags=re.IGNORECASE)
            return cleaned.strip()

        def looks_like_company(candidate: str, title_lower: str) -> bool:
            lower = candidate.lower()
            if not candidate or len(candidate) < 2 or len(candidate) > 80:
                return False
            if lower in {"skip to main content", "sign in", "log in", "apply now", "show more", "show less", "job description", "page content", "linkedin", "linkedin jobs", "home", "about"}:
                return False
            if any(token in lower for token in ["skip to main content", "sign in", "log in", "apply now", "show more", "show less", "job description", "page content", "linkedin"]):
                return False
            if lower in title_lower:
                return False
            if len(candidate.split()) == 1 and candidate.lower() not in {"okta", "model", "tata", "incred"}:
                return False
            return True

        url_name = ""
        if job_url:
            for pattern in [
                r"-at-([a-z0-9-]+)(?:-|$)",
                r"/jobs/view/[^/]+-at-([a-z0-9-]+)(?:-|$)",
            ]:
                url_match = re.search(pattern, job_url.lower())
                if url_match:
                    url_name = url_match.group(1).replace("-", " ").title()
                    break

        if url_name:
            return url_name

        page_text = page_text or ""
        title_lower = (title or "").lower()

        for line in page_text.splitlines():
            cleaned = clean_company_candidate(line)
            if not cleaned:
                continue
            low = cleaned.lower()
            if any(token in low for token in ["skip to main content", "sign in", "log in", "apply now", "show more", "show less", "job description", "page content", "linkedin"]):
                continue

            for pattern in [
                r"\bcompany\s*[:\-]\s*([A-Z][A-Za-z0-9&.,'()\- ]{2,80})",
                r"\bcompany\s+([A-Z][A-Za-z0-9&.,'()\- ]{2,80})",
                r"\bat\s+([A-Z][A-Za-z0-9&.,'()\- ]{2,80})",
                r"\b([A-Z][A-Za-z0-9&.,'()\- ]{2,80})\s+is hiring",
            ]:
                match = re.search(pattern, cleaned)
                if match:
                    company = clean_company_candidate(match.group(1))
                    if looks_like_company(company, title_lower):
                        return company

        title_match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&.,'()\- ]{2,80})", title or "")
        if title_match:
            company = clean_company_candidate(title_match.group(1))
            if looks_like_company(company, title_lower):
                return company

        return "-"

    def write_run_result(self, result: dict):
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_FILE, "a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(result) + "\n")

    def discover_jobs(self):
        logger.info("Looking for jobs across portals: %s", self.portals)
        logger.info("Search keywords: %s", self.keywords)

        discovered_jobs: list[dict[str, str]] = []

        for portal in self.portals:
            try:
                portal_jobs = self.browser.scrape_jobs(portal, self.keywords)
                if portal_jobs:
                    discovered_jobs.extend(portal_jobs)
                else:
                    logger.warning("No jobs were returned from %s. Using fallback job list for this cycle.", portal)
                    discovered_jobs.extend(
                        [
                            {
                                "portal": portal,
                                "title": f"{self.keywords[0].title()} Opportunity",
                                "url": "https://example.com/job",
                            }
                        ]
                    )
            except Exception as exc:
                logger.warning("Could not scrape portal '%s' due to: %s", portal, exc)
                discovered_jobs.extend(
                    [
                        {
                            "portal": portal,
                            "title": f"{self.keywords[0].title()} Opportunity",
                            "url": "https://example.com/job",
                        }
                    ]
                )

        return discovered_jobs

    def apply_to_portal(self, job):
        logger.info("Applying to %s - %s (%s)", job["portal"], job["title"], job["url"])
        page_text = self.browser.read_job_page(job["url"])
        profile_context = self.browser.read_profile_page(self.browser.linkedin_profile_url) if job["portal"].lower() == "linkedin" else ""
        company_name = self.extract_company_name(job["title"], page_text, job["url"])

        matched, score, overlaps = self.resume_matcher.score_job(job["title"], page_text, profile_context)
        logger.info("Resume match score for %s: %.2f | overlaps: %s", job["title"], score, overlaps)

        if not matched:
            logger.info("Skipping %s because the resume does not match the role closely enough.", job["title"])
            return {
                "portal": job["portal"],
                "title": job["title"],
                "company": company_name,
                "url": job["url"],
                "matched": False,
                "applied": False,
                "score": score,
                "overlaps": overlaps,
            }

        applied = self.browser.attempt_apply(job)
        return {
            "portal": job["portal"],
            "title": job["title"],
            "company": company_name,
            "url": job["url"],
            "matched": True,
            "applied": applied,
            "score": score,
            "overlaps": overlaps,
        }

    def run_cycle(self):
        logger.info("Starting daily job search cycle.")
        jobs = self.discover_jobs()
        applied = 0
        matched = 0

        for job in jobs:
            result = self.apply_to_portal(job)
            self.write_run_result(result)
            if result.get("matched"):
                matched += 1
            if result.get("applied"):
                applied += 1

        logger.info("Daily cycle complete. Applied to %s jobs. Matched: %s.", applied, matched)


def build_scheduler(agent: JobAgent) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        agent.run_cycle,
        trigger=CronTrigger(hour=10, minute=0, second=0, timezone="Asia/Kolkata"),
        id="daily-job-application",
        replace_existing=True,
    )
    return scheduler


def main():
    env_file = Path(__file__).with_name(".env")
    env_example_file = Path(__file__).with_name(".env.example")

    load_dotenv(env_file)
    if not env_file.exists() and env_example_file.exists():
        load_dotenv(env_example_file)

    agent = JobAgent()

    if "--test" in sys.argv:
        agent.run_cycle()
        return

    scheduler = build_scheduler(agent)
    logger.info("Scheduler started. Jobs will run every day at 10:00 AM IST.")
    scheduler.start()


if __name__ == "__main__":
    main()
