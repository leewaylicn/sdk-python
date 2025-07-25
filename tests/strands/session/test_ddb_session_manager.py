"""Tests for DynamoDB-based session manager."""

import json
import os
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.session.ddb_session_manager import DDBSessionManager
from strands.types.content import Message, Role
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType


@pytest.mark.skipif(
    os.environ.get("ENABLE_DDB_TESTS") != "true",
    reason="DynamoDB tests are disabled. Set ENABLE_DDB_TESTS=true to enable.",
)
class TestDDBSessionManager(unittest.TestCase):
    """Test DynamoDB-based session manager."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        # Use DynamoDB local or a test table
        cls.table_name = os.environ.get("DDB_TEST_TABLE", "strands-session-test")
        cls.region = os.environ.get("AWS_REGION", "us-east-1")
        
        # Create DynamoDB table for testing if it doesn't exist
        cls._create_test_table()

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment."""
        # Optionally delete the test table
        if os.environ.get("DDB_DELETE_TEST_TABLE") == "true":
            cls._delete_test_table()

    @classmethod
    def _create_test_table(cls):
        """Create DynamoDB table for testing."""
        dynamodb = boto3.client("dynamodb", region_name=cls.region)
        
        try:
            # Check if table exists
            dynamodb.describe_table(TableName=cls.table_name)
            print(f"Test table {cls.table_name} already exists")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Create table
                print(f"Creating test table {cls.table_name}...")
                dynamodb.create_table(
                    TableName=cls.table_name,
                    KeySchema=[
                        {"AttributeName": "session_id", "KeyType": "HASH"},  # Partition key
                        {"AttributeName": "entity_type", "KeyType": "RANGE"},  # Sort key
                    ],
                    AttributeDefinitions=[
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "entity_type", "AttributeType": "S"},
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                
                # Wait for table to be created
                waiter = dynamodb.get_waiter("table_exists")
                waiter.wait(TableName=cls.table_name)
                
                # Enable TTL
                dynamodb.update_time_to_live(
                    TableName=cls.table_name,
                    TimeToLiveSpecification={"AttributeName": "ttl", "Enabled": True},
                )
                
                print(f"Test table {cls.table_name} created")
            else:
                raise

    @classmethod
    def _delete_test_table(cls):
        """Delete DynamoDB test table."""
        dynamodb = boto3.client("dynamodb", region_name=cls.region)
        try:
            dynamodb.delete_table(TableName=cls.table_name)
            print(f"Test table {cls.table_name} deleted")
        except Exception as e:
            print(f"Error deleting test table: {e}")

    def setUp(self):
        """Set up test fixtures."""
        self.session_id = f"test-session-{int(time.time())}"
        self.session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )

    def tearDown(self):
        """Clean up after tests."""
        # Delete test session
        try:
            self.session_manager.delete_session(self.session_id)
        except Exception:
            pass

    def test_create_and_read_session(self):
        """Test creating and reading a session."""
        # Session is created in setUp
        session = self.session_manager.read_session(self.session_id)
        self.assertIsNotNone(session)
        self.assertEqual(session.session_id, self.session_id)
        self.assertEqual(session.session_type, SessionType.AGENT)

    def test_create_agent(self):
        """Test creating an agent in the session."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Read back the agent
        retrieved_agent = self.session_manager.read_agent(self.session_id, agent_id)
        self.assertIsNotNone(retrieved_agent)
        self.assertEqual(retrieved_agent.agent_id, agent_id)

    def test_update_agent(self):
        """Test updating an agent in the session."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        # Create agent
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Update agent
        session_agent.state = {"key": "value"}
        self.session_manager.update_agent(self.session_id, session_agent)
        
        # Read back the agent
        retrieved_agent = self.session_manager.read_agent(self.session_id, agent_id)
        self.assertIsNotNone(retrieved_agent)
        self.assertEqual(retrieved_agent.state, {"key": "value"})

    def test_create_and_read_message(self):
        """Test creating and reading a message."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        # Create agent
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Create message
        message = Message(role=Role.USER, content="Hello, world!")
        session_message = SessionMessage.from_message(message, 0)
        self.session_manager.create_message(self.session_id, agent_id, session_message)
        
        # Read back the message
        retrieved_message = self.session_manager.read_message(self.session_id, agent_id, 0)
        self.assertIsNotNone(retrieved_message)
        self.assertEqual(retrieved_message.role, Role.USER)
        self.assertEqual(retrieved_message.content, "Hello, world!")

    def test_update_message(self):
        """Test updating a message."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        # Create agent
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Create message
        message = Message(role=Role.USER, content="Hello, world!")
        session_message = SessionMessage.from_message(message, 0)
        self.session_manager.create_message(self.session_id, agent_id, session_message)
        
        # Update message
        session_message.content = "Updated content"
        self.session_manager.update_message(self.session_id, agent_id, session_message)
        
        # Read back the message
        retrieved_message = self.session_manager.read_message(self.session_id, agent_id, 0)
        self.assertIsNotNone(retrieved_message)
        self.assertEqual(retrieved_message.content, "Updated content")

    def test_list_messages(self):
        """Test listing messages."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        # Create agent
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Create multiple messages
        for i in range(5):
            message = Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content=f"Message {i}")
            session_message = SessionMessage.from_message(message, i)
            self.session_manager.create_message(self.session_id, agent_id, session_message)
        
        # List all messages
        messages = self.session_manager.list_messages(self.session_id, agent_id)
        self.assertEqual(len(messages), 5)
        
        # Test pagination
        messages = self.session_manager.list_messages(self.session_id, agent_id, limit=2)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].message_id, 0)
        self.assertEqual(messages[1].message_id, 1)
        
        messages = self.session_manager.list_messages(self.session_id, agent_id, offset=2, limit=2)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].message_id, 2)
        self.assertEqual(messages[1].message_id, 3)

    def test_delete_session(self):
        """Test deleting a session."""
        agent_id = "test-agent"
        session_agent = SessionAgent(
            agent_id=agent_id,
            state={},
            conversation_manager_state={},
        )
        
        # Create agent
        self.session_manager.create_agent(self.session_id, session_agent)
        
        # Create message
        message = Message(role=Role.USER, content="Hello, world!")
        session_message = SessionMessage.from_message(message, 0)
        self.session_manager.create_message(self.session_id, agent_id, session_message)
        
        # Delete session
        self.session_manager.delete_session(self.session_id)
        
        # Verify session is deleted
        session = self.session_manager.read_session(self.session_id)
        self.assertIsNone(session)
        
        # Verify agent is deleted
        agent = self.session_manager.read_agent(self.session_id, agent_id)
        self.assertIsNone(agent)
        
        # Verify message is deleted
        message = self.session_manager.read_message(self.session_id, agent_id, 0)
        self.assertIsNone(message)

    def test_agent_initialization_and_restoration(self):
        """Test initializing an agent with the session manager and restoring it."""
        # Create an agent with the session manager
        agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="test-agent",
            session_manager=self.session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=10),
        )
        
        # Add some messages
        agent.messages.append(Message(role=Role.USER, content="Hello!"))
        agent.messages.append(Message(role=Role.ASSISTANT, content="Hi there!"))
        
        # Sync agent to session
        self.session_manager.sync_agent(agent)
        
        # Create a new agent with the same session manager and agent_id
        restored_agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="test-agent",
            session_manager=self.session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=10),
        )
        
        # Verify messages were restored
        self.assertEqual(len(restored_agent.messages), 2)
        self.assertEqual(restored_agent.messages[0].role, Role.USER)
        self.assertEqual(restored_agent.messages[0].content, "Hello!")
        self.assertEqual(restored_agent.messages[1].role, Role.ASSISTANT)
        self.assertEqual(restored_agent.messages[1].content, "Hi there!")


class TestDDBSessionManagerMocked(unittest.TestCase):
    """Test DynamoDB-based session manager with mocked DynamoDB."""

    def setUp(self):
        """Set up test fixtures."""
        self.session_id = "test-session"
        self.table_mock = MagicMock()
        
        # Create a patch for boto3.resource
        self.boto3_resource_patch = patch("boto3.resource")
        self.boto3_resource_mock = self.boto3_resource_patch.start()
        
        # Configure the mock to return our table mock
        self.dynamodb_mock = MagicMock()
        self.dynamodb_mock.Table.return_value = self.table_mock
        self.boto3_resource_mock.return_value = self.dynamodb_mock
        
        # Create session manager with mocked resources
        self.session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name="mock-table",
        )

    def tearDown(self):
        """Clean up after tests."""
        self.boto3_resource_patch.stop()

    def test_create_session_mocked(self):
        """Test creating a session with mocked DynamoDB."""
        # Configure mock to simulate session doesn't exist
        self.table_mock.get_item.return_value = {}
        
        # Create a session
        session = Session(session_id=self.session_id, session_type=SessionType.AGENT)
        result = self.session_manager.create_session(session)
        
        # Verify put_item was called
        self.table_mock.put_item.assert_called_once()
        
        # Verify the result
        self.assertEqual(result.session_id, self.session_id)

    def test_read_session_mocked(self):
        """Test reading a session with mocked DynamoDB."""
        # Configure mock to return a session
        session_data = {
            "session_id": self.session_id,
            "session_type": "AGENT",
        }
        self.table_mock.get_item.return_value = {
            "Item": {
                "session_id": self.session_id,
                "entity_type": "SESSION",
                "data": json.dumps(session_data),
            }
        }
        
        # Read the session
        session = self.session_manager.read_session(self.session_id)
        
        # Verify get_item was called
        self.table_mock.get_item.assert_called_once()
        
        # Verify the result
        self.assertIsNotNone(session)
        self.assertEqual(session.session_id, self.session_id)
        self.assertEqual(session.session_type, SessionType.AGENT)

    def test_error_handling_mocked(self):
        """Test error handling with mocked DynamoDB."""
        # Configure mock to raise an exception
        self.table_mock.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Test error"}},
            "GetItem",
        )
        
        # Verify exception is raised and wrapped
        with self.assertRaises(SessionException):
            self.session_manager.read_session(self.session_id)


if __name__ == "__main__":
    unittest.main()