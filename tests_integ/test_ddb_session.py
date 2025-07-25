"""Integration tests for DynamoDB-based session manager."""

import os
import time
import uuid
from typing import List

import boto3
import pytest

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.session.ddb_session_manager import DDBSessionManager
from strands.types.content import Message
# Role enum uses lowercase values
USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"


@pytest.mark.skipif(
    os.environ.get("ENABLE_DDB_TESTS") != "true",
    reason="DynamoDB tests are disabled. Set ENABLE_DDB_TESTS=true to enable.",
)
class TestDDBSessionIntegration:
    """Integration tests for DynamoDB-based session manager."""

    @classmethod
    def setup_class(cls):
        """Set up test environment."""
        # Use DynamoDB local or a test table
        cls.table_name = os.environ.get("DDB_TEST_TABLE", "strands-session-test")
        cls.region = os.environ.get("AWS_REGION", "us-east-1")
        
        # Create DynamoDB table for testing if it doesn't exist
        cls._create_test_table()

    @classmethod
    def teardown_class(cls):
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
        except Exception:
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

    @classmethod
    def _delete_test_table(cls):
        """Delete DynamoDB test table."""
        dynamodb = boto3.client("dynamodb", region_name=cls.region)
        try:
            dynamodb.delete_table(TableName=cls.table_name)
            print(f"Test table {cls.table_name} deleted")
        except Exception as e:
            print(f"Error deleting test table: {e}")

    def setup_method(self):
        """Set up test fixtures."""
        self.session_id = f"test-{uuid.uuid4()}"
        # Create a new session manager for each test
        self.session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )
        # Reset the _latest_agent_message dictionary
        self.session_manager._latest_agent_message = {}

    def teardown_method(self):
        """Clean up after tests."""
        # Delete test session
        try:
            self.session_manager.delete_session(self.session_id)
        except Exception:
            pass

    def test_agent_with_ddb_session(self):
        """Test agent with DynamoDB session persistence."""
        # Create an agent with the session manager
        agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="test-agent",
            session_manager=self.session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=10),
        )
        
        # Add some messages
        agent.messages.append(Message(role=USER_ROLE, content="Hello!"))
        agent.messages.append(Message(role=ASSISTANT_ROLE, content="Hi there!"))
        
        # Sync agent to session
        self.session_manager.sync_agent(agent)
        
        # Create a new session manager with the same session_id
        new_session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        # Create a new agent with the new session manager and same agent_id
        restored_agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="test-agent",
            session_manager=new_session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=10),
        )
        
        # Verify messages were restored
        assert len(restored_agent.messages) == 2
        assert restored_agent.messages[0].role == USER_ROLE
        assert restored_agent.messages[0].content == "Hello!"
        assert restored_agent.messages[1].role == ASSISTANT_ROLE
        assert restored_agent.messages[1].content == "Hi there!"

    def test_conversation_persistence(self):
        """Test conversation persistence across multiple agents."""
        # Create multiple agents in the same session
        agents = []
        for i in range(3):
            agent = Agent(
                system_prompt=f"You are agent {i}.",
                agent_id=f"agent-{i}",
                session_manager=self.session_manager,
                conversation_manager=SlidingWindowConversationManager(window_size=10),
            )
            agents.append(agent)
            
            # Add messages to each agent
            for j in range(3):
                agent.messages.append(
                    Message(
                        role=USER_ROLE if j % 2 == 0 else ASSISTANT_ROLE,
                        content=f"Message {j} for agent {i}",
                    )
                )
            
            # Sync agent to session
            self.session_manager.sync_agent(agent)
        
        # Create a new session manager with the same session_id
        new_session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        # Create new agents with the new session manager and same agent_ids
        restored_agents = []
        for i in range(3):
            agent = Agent(
                system_prompt=f"You are agent {i}.",
                agent_id=f"agent-{i}",
                session_manager=new_session_manager,
                conversation_manager=SlidingWindowConversationManager(window_size=10),
            )
            restored_agents.append(agent)
        
        # Verify messages were restored for each agent
        for i, agent in enumerate(restored_agents):
            assert len(agent.messages) == 3
            for j in range(3):
                assert agent.messages[j].content == f"Message {j} for agent {i}"

    def test_large_conversation(self):
        """Test handling a large conversation."""
        # Create an agent with the session manager
        agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="large-conversation-agent",
            session_manager=self.session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=100),
        )
        
        # Add many messages
        for i in range(50):
            agent.messages.append(
                Message(
                    role=USER_ROLE if i % 2 == 0 else ASSISTANT_ROLE,
                    content=f"Message {i} with some content to make it larger. This is a test of DynamoDB's ability to handle larger messages efficiently.",
                )
            )
        
        # Sync agent to session
        self.session_manager.sync_agent(agent)
        
        # Create a new session manager with the same session_id
        new_session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        # Create a new agent with the new session manager and same agent_id
        restored_agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="large-conversation-agent",
            session_manager=new_session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=100),
        )
        
        # Verify messages were restored
        assert len(restored_agent.messages) == 50
        for i in range(50):
            assert restored_agent.messages[i].content.startswith(f"Message {i}")

    def test_conversation_window_sliding(self):
        """Test conversation window sliding with DynamoDB session."""
        # Create an agent with a small window size
        agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="window-test-agent",
            session_manager=self.session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=5),
        )
        
        # Add more messages than the window size
        for i in range(10):
            agent.messages.append(
                Message(
                    role=USER_ROLE if i % 2 == 0 else ASSISTANT_ROLE,
                    content=f"Message {i}",
                )
            )
        
        # Sync agent to session
        self.session_manager.sync_agent(agent)
        
        # Create a new session manager with the same session_id
        new_session_manager = DDBSessionManager(
            session_id=self.session_id,
            table_name=self.table_name,
            region_name=self.region,
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        # Create a new agent with the new session manager and same agent_id
        restored_agent = Agent(
            system_prompt="You are a helpful assistant.",
            agent_id="window-test-agent",
            session_manager=new_session_manager,
            conversation_manager=SlidingWindowConversationManager(window_size=5),
        )
        
        # Verify only the last 5 messages were restored (due to window size)
        assert len(restored_agent.messages) == 5
        for i in range(5):
            assert restored_agent.messages[i].content == f"Message {i+5}"


if __name__ == "__main__":
    # Enable tests by setting environment variable
    os.environ["ENABLE_DDB_TESTS"] = "true"
    
    # Run tests
    test = TestDDBSessionIntegration()
    test.setup_class()
    test.setup_method()
    
    try:
        test.test_agent_with_ddb_session()
        print("✅ test_agent_with_ddb_session passed")
        
        test.test_conversation_persistence()
        print("✅ test_conversation_persistence passed")
        
        test.test_large_conversation()
        print("✅ test_large_conversation passed")
        
        test.test_conversation_window_sliding()
        print("✅ test_conversation_window_sliding passed")
    finally:
        test.teardown_method()
        
        # Optionally delete the test table
        if os.environ.get("DDB_DELETE_TEST_TABLE") == "true":
            test.teardown_class()