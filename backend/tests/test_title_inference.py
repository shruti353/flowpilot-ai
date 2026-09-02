from app.agent.title_inference import infer_meeting_title


def test_infers_title_from_meeting_with_the_x_team():
    assert (
        infer_meeting_title("Schedule a meeting with the AI team for tomorrow at 3 PM")
        == "AI Team Meeting"
    )


def test_infers_title_from_meeting_with_my_x_team():
    assert (
        infer_meeting_title("Schedule a meeting with my AI team tomorrow at 3 PM.")
        == "AI Team Meeting"
    )


def test_infers_title_from_meeting_with_x_team_no_article():
    assert infer_meeting_title("Set up a meeting with Sales team next Monday") == "Sales Team Meeting"


def test_infers_title_from_meeting_with_acronym_team_no_article():
    assert infer_meeting_title("Set up a meeting with AI team next Monday") == "AI Team Meeting"


def test_infers_title_from_article_x_meeting():
    assert infer_meeting_title("Schedule a marketing meeting for Friday") == "Marketing Meeting"


def test_infers_title_from_an_x_meeting():
    assert infer_meeting_title("Set up an urgent client meeting tomorrow") == "Urgent Client Meeting"


def test_returns_none_when_no_recognizable_phrasing():
    assert infer_meeting_title("Schedule a meeting tomorrow.") is None


def test_returns_none_for_unrelated_request():
    assert infer_meeting_title("Send an email to John about the invoice.") is None


def test_returns_none_for_empty_text():
    assert infer_meeting_title("") is None
