"""Setup's last page: what the other steps chose; finishing writes the settings file."""

from ama.setup import Step

STEP = Step(slug="ready", title="Ready", order=90, template="setup/ready.html",
            button="Finish and start AMA")
