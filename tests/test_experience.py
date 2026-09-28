from datetime import date

from scoring.experience import years_pm_experience


def test_single_pm_role_resolves_present():
    roles = [
        {"title": "Product Manager", "company": "Portwise", "start": "Apr 2023", "end": "Present",
         "is_product_management_role": True},
    ]
    years = years_pm_experience(roles, reference_date=date(2025, 4, 1))
    assert 1.9 <= years <= 2.1


def test_non_pm_roles_excluded():
    roles = [
        {"title": "Senior Supply Chain Analyst", "company": "Mahindra", "start": "Sep 2021", "end": "Mar 2023",
         "is_product_management_role": False},
        {"title": "Product Manager", "company": "Portwise", "start": "Apr 2023", "end": "Present",
         "is_product_management_role": True},
    ]
    years = years_pm_experience(roles, reference_date=date(2025, 4, 1))
    assert 1.9 <= years <= 2.1


def test_continuous_apm_and_pm_roles_sum():
    roles = [
        {"title": "Associate Product Manager", "company": "Springboard", "start": "Jul 2020", "end": "Dec 2021",
         "is_product_management_role": True},
        {"title": "Product Manager", "company": "Springboard", "start": "Jan 2022", "end": "Present",
         "is_product_management_role": True},
    ]
    years = years_pm_experience(roles, reference_date=date(2023, 6, 1))
    assert 2.8 <= years <= 3.0


def test_no_pm_roles_returns_zero():
    roles = [
        {"title": "Marketing Manager", "company": "Ventus", "start": "Jun 2021", "end": "Present",
         "is_product_management_role": False},
    ]
    assert years_pm_experience(roles, reference_date=date(2025, 6, 1)) == 0.0


def test_overlapping_pm_roles_not_double_counted():
    roles = [
        {"title": "PM", "company": "A", "start": "Jan 2020", "end": "Jan 2022", "is_product_management_role": True},
        {"title": "PM", "company": "B", "start": "Jun 2021", "end": "Jun 2022", "is_product_management_role": True},
    ]
    years = years_pm_experience(roles, reference_date=date(2023, 1, 1))
    assert 2.4 <= years <= 2.6
