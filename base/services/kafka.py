import json

from django.conf import settings
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from kafka.structs import OffsetAndMetadata


# Logic for doing basic operations, like making topic and connecting to kafka
# Subclasses only declare TOPICS and GROUP_ID, and add their own publish methods
class KafkaQueue:
    TOPICS = []
    GROUP_ID = None
    MAX_POLL_RECORDS = 1
    SEND_TIMEOUT = 10

    _producer = None

    # This is used to write to the queue,
    # It forms a connection that sends data to the broker(kafka server)
    # Stored on KafkaQueue and not cls, so every subclass shares the one producer
    @classmethod
    def producer(cls):
        if KafkaQueue._producer is None:
            KafkaQueue._producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
            )
        return KafkaQueue._producer

    @classmethod
    def ensure_topics(cls):
        # Here we are making topics and making one partation in it
        admin = KafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        try:
            for name in cls.TOPICS:
                try:
                    admin.create_topics([
                        NewTopic(name=name, num_partitions=1, replication_factor=1)
                    ])
                except TopicAlreadyExistsError:
                    pass
        finally:
            admin.close()

    @classmethod
    def partition(cls, topic):
        return TopicPartition(topic, 0)

    @classmethod
    def consumer(cls):
        consumer = KafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=cls.GROUP_ID,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            max_poll_records=cls.MAX_POLL_RECORDS,
        )
        consumer.assign([cls.partition(t) for t in cls.TOPICS])
        return consumer

    @classmethod
    def send(cls, topic, payload):
        # send sends the msg, get takes the output once it is available
        cls.producer().send(topic, payload).get(timeout=cls.SEND_TIMEOUT)
        return topic

    @classmethod
    def commit(cls, consumer, record):
        # offset + 1 is the next offset we want, not the one we just handled
        consumer.commit({
            TopicPartition(record.topic, record.partition):
                OffsetAndMetadata(record.offset + 1, "", -1)
        })
