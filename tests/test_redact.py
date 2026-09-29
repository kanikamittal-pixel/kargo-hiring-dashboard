from ingestion.redact import _looks_corrupted, extract_contact_info


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
