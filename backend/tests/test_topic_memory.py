from src.app.services.topic_memory import find_duplicate_topic, load_topic_memory


def test_topic_memory_keeps_full_history():
    rows = [(f"Unique topic {index}", "published") for index in range(501)]

    class FakeQuery:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return rows

    class FakeSession:
        def query(self, *args):
            return FakeQuery()

    memory = load_topic_memory(FakeSession(), profile_id=1)

    assert len(memory) == 501
    assert memory[-1] == ("Unique topic 500", "published")


def test_topic_memory_rejects_exact_topic_after_long_history():
    memory = [(f"Unique topic {index}", "published") for index in range(500)]
    memory.append(("Python async testing", "scheduled"))

    duplicate = find_duplicate_topic("Python async testing", memory)

    assert duplicate == ("Python async testing", "scheduled", 1.0)


def test_topic_memory_allows_distinct_topic_after_long_history():
    memory = [(f"Unique topic {index}", "published") for index in range(501)]

    duplicate = find_duplicate_topic("Database connection pooling", memory)

    assert duplicate is None
