from base.services.kafka import KafkaQueue


# Document specific topics and enqueue policy, the kafka plumbing lives in base
class DocumentQueue(KafkaQueue):
    TOPIC_NORMAL = "docs.process"
    TOPIC_PRIORITY = "docs.process.priority"
    # Not making seperate partitions for this as if we need to add more partations in future, the priority partation concept will not work
    TOPICS = [TOPIC_NORMAL, TOPIC_PRIORITY]

    GROUP_ID = "doc-embedder"

    @classmethod
    def publish(cls, doc, priority=False, user=None):
        topic = cls.TOPIC_PRIORITY if priority else cls.TOPIC_NORMAL

        cls.send(topic, doc.as_message())
        # send blocks until kafka confirms, so we mark the document as queued only after
        # the message has really reached the broker. This saves us in case kafka is down

        doc.status = "queued"
        doc.workflow_run_id = ""
        fields = ["status", "workflow_run_id", "updated_at"]
        if user is not None:
            doc.updated_by = user
            fields.append("updated_by")
        doc.save(update_fields=fields)
        return topic
