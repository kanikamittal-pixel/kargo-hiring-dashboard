from ingestion.redact import _looks_corrupted, _name_from_filename, extract_contact_info


def test_detects_doubled_letter_corruption():
    # Real-world case: a PDF that fakes a bold header by double-printing it caused
    # pdfplumber to interleave the two overlapping copies into garbage.
    assert _looks_corrupted("RROohHaAnN M MehEtHaTA") is True


def test_does_not_flag_real_names():
    for name in [
        "Rohan Desai", "Sunita Krishnamurthy", "Vikram Nair", "Aditya Shetty",
        "Preetham Rao", "Meghna Tiwari", "Lavanya Iyer", "RAHUL BOSE",
        "McKinsey Consultant", "O'Brien Smith", "Jean-Pierre Dubois",
        "ALL CAPS NAME HERE",
    ]:
        assert _looks_corrupted(name) is False, f"false positive on {name!r}"


def test_extract_contact_info_drops_corrupted_name_instead_of_using_it():
    corrupted_text = (
        "RROohHaAnN M MehEtHaTA\n"
        "Strategy & Operations Leader\n"
        "+91 9820928 210123 4151345 squad_1@pg27.mesaschool.co rohan-mehta\n"
        "PROFESSIONAL SUMMARY\n"
        "Strategic Partner to Executive Leadership with ~4 years of experience.\n"
    )
    contact = extract_contact_info(corrupted_text)
    assert contact["name"] is None
    assert contact["email"] == "squad_1@pg27.mesaschool.co"


def test_filename_fallback_used_when_body_extraction_fails():
    corrupted_text = (
        "RROohHaAnN M MehEtHaTA\n"
        "Strategy & Operations Leader\n"
        "+91 9820928 210123 4151345 squad_1@pg27.mesaschool.co rohan-mehta\n"
    )
    contact = extract_contact_info(corrupted_text, filename="01_rohan_mehta.pdf")
    assert contact["name"] == "Rohan Mehta"


def test_name_from_filename():
    assert _name_from_filename("01_rohan_mehta.pdf") == "Rohan Mehta"
    assert _name_from_filename("John Smith Resume.pdf") == "John Smith"
    assert _name_from_filename("Resume_Final.pdf") is None
    assert _name_from_filename("resume2024.pdf") is None
    assert _name_from_filename("candidate123.pdf") is None


def test_does_not_extract_institution_name_as_candidate_name():
    # Real-world case: the actual name line didn't match the strict name pattern (a title
    # right below it, or a layout quirk), so extraction fell through to a line that is
    # also "2-4 capitalized words with no digits" -- but is a university, not a person.
    text = (
        "Indian Institute of Management, Ahmedabad\n"
        "Delhi University\n"
        "squad_2@pg27.mesaschool.co\n"
        "PROFESSIONAL SUMMARY\n"
        "Product leader with 6 years of experience.\n"
    )
    contact = extract_contact_info(text)
    assert contact["name"] is None

    assert _name_from_filename("Delhi_University.pdf") is None
