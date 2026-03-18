from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


class KafkaTransactionConsumer:
    def __init__(self, bootstrap_servers: str, topic: str = "transactions", group_id: str = "aml-processor"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.processor: Optional[Callable[[Dict[str, Any]], Any]] = None
        self.running = False

    async def start(self, processor: Callable[[Dict[str, Any]], Any]) -> None:
        self.processor = processor
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            max_poll_records=100,
        )
        await self.consumer.start()
        self.running = True
        try:
            async for msg in self.consumer:
                if not self.running:
                    break
                if self.processor is None:
                    continue
                try:
                    await self.processor(msg.value)
                except Exception as e:
                    await self._send_to_dlq(msg.value, str(e))
        finally:
            await self.consumer.stop()

    async def stop(self) -> None:
        self.running = False
        if self.consumer:
            await self.consumer.stop()

    async def _send_to_dlq(self, message: Dict[str, Any], error: str) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        try:
            dlq_message = {
                "original_message": message,
                "error": error,
                "timestamp": datetime.utcnow().isoformat(),
                "retry_count": int(message.get("retry_count", 0)) + 1,
            }
            await producer.send(f"{self.topic}-dlq", dlq_message)
        finally:
            await producer.stop()


class KafkaAlertProducer:
    def __init__(self, bootstrap_servers: str):
        self._bootstrap_servers = bootstrap_servers
        self.producer: Optional[AIOKafkaProducer] = None

    async def start(self) -> None:
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self.producer.start()

    async def stop(self) -> None:
        if self.producer:
            await self.producer.stop()
            self.producer = None

    async def send_alert(self, alert: Dict[str, Any]) -> None:
        if not self.producer:
            raise RuntimeError("Kafka producer not started")
        await self.producer.send("alerts", alert)

    async def send_model_update(self, model_update: Dict[str, Any]) -> None:
        if not self.producer:
            raise RuntimeError("Kafka producer not started")
        await self.producer.send("model-updates", model_update)

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


class KafkaTransactionConsumer:
    def __init__(self, bootstrap_servers: str, topic: str = "transactions", group_id: str = "aml-processor"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.processor: Optional[Callable[[Dict[str, Any]], Any]] = None
        self.running = False

    async def start(self, processor: Callable[[Dict[str, Any]], Any]) -> None:
        self.processor = processor
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            max_poll_records=100,
        )
        await self.consumer.start()
        self.running = True
        try:
            async for msg in self.consumer:
                if not self.running:
                    break
                if self.processor is None:
                    continue
                try:
                    await self.processor(msg.value)
                except Exception as e:
                    await self._send_to_dlq(msg.value, str(e))
        finally:
            await self.consumer.stop()

    async def stop(self) -> None:
        self.running = False
        if self.consumer:
            await self.consumer.stop()

    async def _send_to_dlq(self, message: Dict[str, Any], error: str) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        try:
            dlq_message = {
                "original_message": message,
                "error": error,
                "timestamp": datetime.utcnow().isoformat(),
                "retry_count": int(message.get("retry_count", 0)) + 1,
            }
            await producer.send(f"{self.topic}-dlq", dlq_message)
        finally:
            await producer.stop()


class KafkaAlertProducer:
    def __init__(self, bootstrap_servers: str):
        self._bootstrap_servers = bootstrap_servers
        self.producer: Optional[AIOKafkaProducer] = None

    async def start(self) -> None:
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self.producer.start()

    async def stop(self) -> None:
        if self.producer:
            await self.producer.stop()
            self.producer = None

    async def send_alert(self, alert: Dict[str, Any]) -> None:
        if not self.producer:
            raise RuntimeError("Kafka producer not started")
        await self.producer.send("alerts", alert)

    async def send_model_update(self, model_update: Dict[str, Any]) -> None:
        if not self.producer:
            raise RuntimeError("Kafka producer not started")
        await self.producer.send("model-updates", model_update)

