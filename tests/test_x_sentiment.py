import os
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from x_sentiment import (
    find_latest_phase3,
    parse_phase3_file,
    classify_tweet,
    compute_rating,
    build_markdown,
    run_sentiment,
)
