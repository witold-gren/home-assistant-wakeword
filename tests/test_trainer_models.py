"""Which kept model is best and why (card 6: Models)."""

from wakeword.trainer.models import best_point, rank

# the runs of 2026-10-28 (final tests)
RUN_3 = [[1.0, 1.0, 0.0], [0.99, 0.1097, 0.375], [0.98, 0.093, 0.562], [0.93, 0.0629, 0.75], [0.86, 0.0465, 1.312]]
RUN_4 = [[1.0, 1.0, 0.0], [0.99, 0.073, 0.937], [0.98, 0.0616, 1.125], [0.96, 0.0491, 1.875]]
READY = [[0.99, 0.06, 0.1], [0.97, 0.04, 0.3], [0.95, 0.03, 0.6]]


def test_a_model_is_judged_at_its_most_balanced_cutoff():
    point = best_point(RUN_3)
    assert point["cutoff"] == 0.93 and point["times"] == 1.5 and not point["ready"]  # 0.75/h is 1.5× 0.5
    assert best_point(RUN_4)["times"] == 1.874  # 0.937/h at 0.99
    ready = best_point(READY)
    assert ready["ready"] and ready["cutoff"] == 0.97  # the lowest cutoff that meets both goals
    assert best_point([[1.0, 1.0, 0.0]]) is None and best_point([]) is None  # never wakes: no answer


def test_the_closest_to_the_goals_is_best():
    listing = {"models": [{"id": "b", "auc": 0.56, "roc": RUN_4}, {"id": "a", "auc": 0.30, "roc": RUN_3},
                          {"id": "c", "auc": None, "roc": []}]}
    ranked = rank(listing)
    assert ranked["best"] == "a" and ranked["models"][2]["score"] is None
    # the same distance from the goals: the smaller AUC decides
    tie = rank({"models": [{"id": "x", "auc": 0.4, "roc": RUN_3}, {"id": "y", "auc": 0.2, "roc": RUN_3}]})
    assert tie["best"] == "y"
    assert rank({"models": []})["best"] is None


def test_the_model_to_export_is_named(tmp_path):
    import json

    from wakeword.trainer.models import local_model

    build = tmp_path / "hej_jarvis"
    (build / "trained").mkdir(parents=True)
    assert local_model(build) is None  # nothing trained here
    (build / "trained" / "best_weights.weights.h5").write_bytes(b"run-3")
    for model_id, weights, name in (("20261028-212257", b"run-1", "cichy_słonecznik"), ("20261028-222907", b"run-3", "wolny_wiatr")):
        (build / "models" / model_id).mkdir(parents=True)
        (build / "models" / model_id / "best_weights.weights.h5").write_bytes(weights)
        (build / "models" / model_id / "run.json").write_text(json.dumps({"name": name}))
    assert local_model(build) == {"id": "20261028-222907", "name": "wolny_wiatr", "number": 2}
    (build / "trained" / "best_weights.weights.h5").write_bytes(b"something else")
    assert local_model(build) is None  # trained before models were kept, or not fetched again



def test_household_test_ranked_apart_from_the_neutral_one():
    def household(times, cutoff=0.95):
        return {"hours": 0.3, "takes": {"tomek": 3}, "best": {"cutoff": cutoff, "times": times, "frr_worst": 0.0,
                                                                "missed": {"tomek": 0}, "false_wakes": 0, "ready": times <= 1}}

    listing = rank({"models": [
        {"id": "a", "auc": 0.30, "roc": RUN_3, "household": household(4.0)},  # best for anyone
        {"id": "b", "auc": 0.56, "roc": RUN_4, "household": household(0.8)},  # best at home
        {"id": "c", "auc": 0.40, "roc": RUN_4, "household": None},  # not measured yet
        {"id": "d", "auc": 0.40, "roc": RUN_4, "household": {"hours": 0, "takes": {}, "best": None}}]})
    assert listing["best"] == "a" and listing["best_household"] == "b"
    assert listing["models"][1]["household_score"]["ready"] and listing["models"][2]["household_score"] is None
    assert listing["models"][3]["household_score"] is None
    # the same household score (a few takes): the neutral test decides
    tie = rank({"models": [{"id": "x", "auc": 0.5, "roc": RUN_4, "household": household(1.0)},
                           {"id": "y", "auc": 0.3, "roc": RUN_3, "household": household(1.0)}]})
    assert tie["best_household"] == "y"
    assert rank({"models": [{"id": "z", "auc": None, "roc": []}]})["best_household"] is None
