"""Setup's first page: what AMA is, and that this takes a minute."""

from ama.setup import Step

STEP = Step(slug="welcome", title="Welcome to AMA", order=10,
            template="setup/welcome.html", button="Get started")
