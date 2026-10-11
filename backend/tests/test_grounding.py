from app.grounding import REVIEW_REASON, check


def turns(*pairs):
    return [{"role": r, "message": m} for r, m in pairs]


def test_lf1631_invented_critical_reason_is_cleared():
    # The real bug: critical reason nowhere in what the caller said
    case = {
        "critical_reason": "Woman not breathing after being pulled from water",
        "transcript": turns(
            ("agent", "Is anyone not breathing or unconscious?"),
            ("user", "The water's at my chest and rising. My grandmother is on oxygen and the power's out."),
        ),
    }
    changes = check(case)
    assert changes["critical_reason"] is None
    assert changes["needs_review"] is True and changes["review_reason"] == REVIEW_REASON


def test_agent_words_do_not_count():
    case = {"injuries": "bleeding", "transcript": turns(("agent", "Is anyone bleeding?"), ("user", "No, we are fine"))}
    assert check(case)["injuries"] is None


def test_grounded_details_are_kept():
    case = {
        "critical_reason": "Neighbor is unconscious",
        "injuries": "Gunshot wound to stomach, bleeding",
        "medical_needs": ["insulin"],
        "transcript": turns(("user", "My neighbor got shot in the stomach and is bleeding, he's unconscious. He needs insulin.")),
    }
    assert check(case) is None


def test_spanish_call_checked_against_english_translation():
    case = {
        "critical_reason": "Elderly man unconscious",
        "medical_needs": ["insulin"],
        "transcript": turns(("user", "Mi papá está inconsciente y necesita su insulina.")),
        "transcript_en": [{"role": "caller", "message": "My dad is unconscious and needs his insulin."}],
    }
    assert check(case) is None  # not flagged just because the call was in Spanish


def test_untranslated_non_english_call_is_not_flagged():
    # LF-1622: Hindi caller ("there's a fire and my son is hurt"), no English translation available
    case = {
        "critical_reason": "Fire reported and son is injured",
        "transcript": turns(("user", "Hello."), ("user", "Ya toh aag laga hua hai aur mere bete ko chot lagi hui hai."),
                            ("user", "Your street address is 4173 Elgin Street, Houston, Texas.")),
    }
    assert check(case) is None


def test_only_ungrounded_medical_items_are_dropped():
    case = {"medical_needs": ["oxygen", "dialysis"], "transcript": turns(("user", "grandma is on oxygen"))}
    changes = check(case)
    assert changes["medical_needs"] == ["oxygen"]


def test_post_text_is_the_source_for_social_cases():
    case = {"injuries": "broken leg", "transcript": turns(("user", "HELP my brother broke his leg, stuck at 5200 Bellfort"))}
    assert check(case) is None


def test_no_caller_turns_means_nothing_to_check():
    assert check({"critical_reason": "anything", "transcript": []}) is None
