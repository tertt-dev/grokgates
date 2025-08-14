#!/usr/bin/env python3
"""
Clear all Redis data for Grokgates v6
WARNING: This will delete ALL data including conversations, memories, and beacons
"""
import redis
import sys
import config

def clear_all_redis():
    """Clear all Redis data with confirmation"""
    
    # Connect to Redis
    try:
        client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True
        )
        client.ping()
        print("✓ Connected to Redis server")
    except redis.ConnectionError:
        print("✗ Redis server not available. Please ensure Redis is running.")
        return False
    
    # Get all keys
    all_keys = client.keys('*')
    
    if not all_keys:
        print("Redis is already empty - no data to clear")
        return True
    
    # Show what will be deleted
    print("\n" + "="*50)
    print("WARNING: This will delete ALL Redis data!")
    print("="*50)
    print(f"\nFound {len(all_keys)} keys to delete:")
    
    # Categorize keys
    categories = {
        'conversations': [],
        'memories': [],
        'beacon': [],
        'board': [],
        'proposals': [],
        'plans': [],
        'other': []
    }
    
    for key in all_keys:
        if key.startswith('conv'):
            categories['conversations'].append(key)
        elif 'memory' in key.lower() or 'chroma' in key.lower():
            categories['memories'].append(key)
        elif 'beacon' in key.lower():
            categories['beacon'].append(key)
        elif 'board' in key.lower():
            categories['board'].append(key)
        elif 'proposal' in key.lower():
            categories['proposals'].append(key)
        elif key in ['plans', 'plan_list', 'dominance_plans']:
            categories['plans'].append(key)
        else:
            categories['other'].append(key)
    
    # Display categories
    for category, keys in categories.items():
        if keys:
            print(f"\n{category.upper()} ({len(keys)} keys):")
            for key in keys[:5]:  # Show first 5
                print(f"  - {key}")
            if len(keys) > 5:
                print(f"  ... and {len(keys) - 5} more")
    
    # Ask for confirmation
    print("\n" + "="*50)
    response = input("Are you sure you want to delete ALL data? Type 'YES' to confirm: ")
    
    if response != 'YES':
        print("Cancelled - no data was deleted")
        return False
    
    # Delete all keys
    print("\nDeleting all Redis data...")
    for key in all_keys:
        client.delete(key)
    
    print(f"✓ Successfully deleted {len(all_keys)} keys")
    
    # Verify deletion
    remaining = client.keys('*')
    if remaining:
        print(f"⚠ Warning: {len(remaining)} keys still remain")
        return False
    else:
        print("✓ Redis is now completely empty")
        return True

def clear_specific_types():
    """Clear specific types of data"""
    
    # Connect to Redis
    try:
        client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True
        )
        client.ping()
        print("✓ Connected to Redis server")
    except redis.ConnectionError:
        print("✗ Redis server not available. Please ensure Redis is running.")
        return False
    
    print("\nWhat would you like to clear?")
    print("1. Conversations only")
    print("2. Beacon feed only")
    print("3. Board messages only")
    print("4. Memories only")
    print("5. Dominance plans only")
    print("6. Everything (same as --all)")
    print("7. Cancel")
    
    choice = input("\nEnter choice (1-6): ")
    
    patterns = {
        '1': ['conv:*', 'conversations', 'conversation_list', 'frontend_typing'],
        '2': ['beacon_feed', 'beacon_formatted'],
        '3': ['shared_board'],
        '4': ['*memory*', '*chroma*'],
        '5': ['plans', 'plan_list', 'dominance_plans', 'latest_dominance_protocol'],
        '6': ['*']
    }
    
    if choice == '7':
        print("Cancelled")
        return False
    
    if choice not in patterns:
        print("Invalid choice")
        return False
    
    if choice == '6':
        return clear_all_redis()
    
    # Get matching keys
    keys_to_delete = []
    for pattern in patterns[choice]:
        keys_to_delete.extend(client.keys(pattern))
    
    if not keys_to_delete:
        print("No matching data found")
        return True
    
    # Remove duplicates
    keys_to_delete = list(set(keys_to_delete))
    
    print(f"\nFound {len(keys_to_delete)} keys to delete:")
    for key in keys_to_delete[:10]:
        print(f"  - {key}")
    if len(keys_to_delete) > 10:
        print(f"  ... and {len(keys_to_delete) - 10} more")
    
    response = input("\nProceed with deletion? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled")
        return False
    
    # Delete keys
    for key in keys_to_delete:
        client.delete(key)
    
    print(f"✓ Successfully deleted {len(keys_to_delete)} keys")
    return True

def main():
    """Main function"""
    print("""
╔═══════════════════════════════════════════════════════╗
║        GROKGATES v6 - REDIS DATA CLEANER              ║
╚═══════════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        # Direct clear all
        clear_all_redis()
    else:
        # Interactive mode
        clear_specific_types()

if __name__ == "__main__":
    main()