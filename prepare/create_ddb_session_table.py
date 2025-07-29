#!/usr/bin/env python3
"""
Create DynamoDB table for Strands session storage
"""

import argparse
import boto3
import time
from botocore.exceptions import ClientError

def create_session_table(table_name, region=None):
    """Create DynamoDB table for session storage"""
    
    print(f"🚀 Creating DynamoDB table: {table_name}")
    print("=" * 50)
    
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.client('dynamodb', region_name=region)
        
        # Check if table already exists
        try:
            response = dynamodb.describe_table(TableName=table_name)
            print(f"✅ Table '{table_name}' already exists")
            print(f"📊 Status: {response['Table']['TableStatus']}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise e
            # Table doesn't exist, continue to create it
        
        # Create table
        print(f"📋 Creating table '{table_name}'...")
        
        table_definition = {
            'TableName': table_name,
            'KeySchema': [
                {
                    'AttributeName': 'session_id',
                    'KeyType': 'HASH'  # Partition key
                },
                {
                    'AttributeName': 'entity_type',
                    'KeyType': 'RANGE'  # Sort key
                }
            ],
            'AttributeDefinitions': [
                {
                    'AttributeName': 'session_id',
                    'AttributeType': 'S'  # String
                },
                {
                    'AttributeName': 'entity_type',
                    'AttributeType': 'S'  # String
                }
            ],
            'BillingMode': 'PAY_PER_REQUEST',  # On-demand billing
            'Tags': [
                {
                    'Key': 'Application',
                    'Value': 'StrandsAgents'
                },
                {
                    'Key': 'Purpose',
                    'Value': 'SessionStorage'
                }
            ]
        }
        
        # Create the table
        response = dynamodb.create_table(**table_definition)
        
        print(f"⏳ Table creation initiated...")
        print(f"📋 Table ARN: {response['TableDescription']['TableArn']}")
        
        # Wait for table to be created
        print("⏳ Waiting for table to become active...")
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(
            TableName=table_name,
            WaiterConfig={
                'Delay': 5,
                'MaxAttempts': 20
            }
        )
        
        # Verify table status
        response = dynamodb.describe_table(TableName=table_name)
        table_status = response['Table']['TableStatus']
        
        if table_status == 'ACTIVE':
            print(f"✅ Table '{table_name}' created successfully!")
            print(f"📊 Status: {table_status}")
            print(f"🔑 Partition Key: session_id (String)")
            print(f"🔑 Sort Key: entity_type (String)")
            print(f"💰 Billing Mode: Pay-per-request")
            
            # Enable TTL
            try:
                print("⏳ Enabling TTL on 'ttl' attribute...")
                dynamodb.update_time_to_live(
                    TableName=table_name,
                    TimeToLiveSpecification={
                        'AttributeName': 'ttl',
                        'Enabled': True
                    }
                )
                print("✅ TTL enabled successfully")
            except Exception as ttl_error:
                print(f"⚠️ TTL setup failed: {ttl_error}")
                print("ℹ️ You can enable TTL manually in AWS Console")
            
            return True
        else:
            print(f"⚠️ Table created but status is: {table_status}")
            return False
            
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'AccessDeniedException':
            print(f"❌ Access denied: {error_message}")
            print("💡 Please ensure your AWS credentials have DynamoDB permissions:")
            print("   - dynamodb:CreateTable")
            print("   - dynamodb:DescribeTable")
            print("   - dynamodb:UpdateTimeToLive")
        else:
            print(f"❌ AWS Error ({error_code}): {error_message}")
        
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_table_access(table_name, region=None):
    """Test basic table operations"""
    
    print(f"\n🧪 Testing table access...")
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name=region)
        table = dynamodb.Table(table_name)
        
        # Test put item
        test_item = {
            'session_id': 'test_session_123',
            'entity_type': 'SESSION',
            'data': '{"test": "data"}',
            'ttl': int(time.time()) + 3600,  # 1 hour from now
            'created_at': '2025-07-23T15:00:00Z'
        }
        
        table.put_item(Item=test_item)
        print("✅ Test item created")
        
        # Test get item
        response = table.get_item(Key={'session_id': 'test_session_123', 'entity_type': 'SESSION'})
        if 'Item' in response:
            print("✅ Test item retrieved")
        
        # Test delete item
        table.delete_item(Key={'session_id': 'test_session_123', 'entity_type': 'SESSION'})
        print("✅ Test item deleted")
        
        print("✅ All table operations successful!")
        return True
        
    except Exception as e:
        print(f"❌ Table access test failed: {e}")
        return False

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Create DynamoDB table for Strands session storage')
    parser.add_argument('--table-name', default='strands-sessions', help='DynamoDB table name')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--skip-test', action='store_true', help='Skip table access test')
    args = parser.parse_args()
    
    print("🎯 Strands Agents - DynamoDB Session Storage Setup")
    print("=" * 60)
    
    # Check AWS credentials
    try:
        sts = boto3.client('sts', region_name=args.region)
        identity = sts.get_caller_identity()
        print(f"✅ AWS credentials configured")
        print(f"📋 Account: {identity.get('Account', 'Unknown')}")
        print(f"👤 User/Role: {identity.get('Arn', 'Unknown')}")
    except Exception as e:
        print(f"❌ AWS credentials not configured: {e}")
        print("💡 Configure AWS credentials using:")
        print("   aws configure")
        print("   or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        return
    
    # Create table
    if create_session_table(args.table_name, args.region):
        # Test table access
        if not args.skip_test:
            test_table_access(args.table_name, args.region)
        
        print("\n" + "=" * 60)
        print("🎉 DynamoDB Setup Complete!")
        print("\n💡 Next steps:")
        print("  1. Run integration tests: python -m pytest tests_integ/test_ddb_session.py -v")
        print("  2. Use DDBSessionManager in your application")
        print("  3. Monitor DynamoDB usage in AWS Console")
    else:
        print("\n❌ DynamoDB setup failed")
        print("💡 Check AWS permissions and try again")

if __name__ == "__main__":
    main()