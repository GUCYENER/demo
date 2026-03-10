"""
Role Permissions Tablosu Oluşturma Script'i
"""
import sys
sys.path.insert(0, '.')

from app.core.db import get_db_context

def create_permissions_table():
    """role_permissions tablosunu oluştur"""
    
    sql = '''
    -- Role Permissions Table
    CREATE TABLE IF NOT EXISTS role_permissions (
        id SERIAL PRIMARY KEY,
        role_name VARCHAR(50) NOT NULL,
        resource_type VARCHAR(50) NOT NULL,
        resource_id VARCHAR(100) NOT NULL,
        resource_label VARCHAR(200),
        parent_resource_id VARCHAR(100),
        can_view BOOLEAN DEFAULT FALSE,
        can_create BOOLEAN DEFAULT FALSE,
        can_update BOOLEAN DEFAULT FALSE,
        can_delete BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(role_name, resource_type, resource_id)
    );

    -- Index for faster lookups
    CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_name);
    CREATE INDEX IF NOT EXISTS idx_role_permissions_resource ON role_permissions(resource_type, resource_id);
    '''
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
                print("✅ role_permissions tablosu oluşturuldu!")
                return True
    except Exception as e:
        print(f"❌ Hata: {e}")
        return False

def seed_admin_permissions():
    """Admin için varsayılan yetkileri ekle"""
    
    # Tüm kaynaklar listesi
    resources = [
        # Menüler
        ('menu', 'menuNewTicket', 'Ana Sayfa', None),
        ('menu', 'menuParameters', 'Parametreler', None),
        ('menu', 'menuKnowledgeBase', 'Bilgi Tabanı', None),
        ('menu', 'menuAuthorization', 'Yetkilendirme', None),
        ('menu', 'menuOrganizations', 'Organizasyonlar', None),
        ('menu', 'menuProfile', 'Profilim', None),
        
        # Parametreler altındaki sekmeler
        ('tab', 'tabLlmConfig', 'LLM Tanımları', 'menuParameters'),
        ('tab', 'tabPromptDesign', 'Prompt Dizayn', 'menuParameters'),
        ('tab', 'tabMLTraining', 'Model Eğitim', 'menuParameters'),
        ('tab', 'tabSystemReset', 'Sistem Sıfırlama', 'menuParameters'),
    ]
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                # Admin için tüm yetkiler
                for resource_type, resource_id, label, parent in resources:
                    cur.execute('''
                        INSERT INTO role_permissions 
                        (role_name, resource_type, resource_id, resource_label, parent_resource_id, 
                         can_view, can_create, can_update, can_delete)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (role_name, resource_type, resource_id) 
                        DO UPDATE SET 
                            resource_label = EXCLUDED.resource_label,
                            parent_resource_id = EXCLUDED.parent_resource_id,
                            can_view = EXCLUDED.can_view,
                            can_create = EXCLUDED.can_create,
                            can_update = EXCLUDED.can_update,
                            can_delete = EXCLUDED.can_delete,
                            updated_at = NOW()
                    ''', ('admin', resource_type, resource_id, label, parent, True, True, True, True))
                
                # User için varsayılan yetkiler (sadece temel erişim)
                user_permissions = {
                    'menuNewTicket': (True, True, False, False),
                    'menuParameters': (True, False, False, False),
                    'menuKnowledgeBase': (True, True, False, False),
                    'menuProfile': (True, False, True, False),
                    'tabLlmConfig': (True, False, False, False),
                    'tabPromptDesign': (True, False, False, False),
                }
                
                for resource_type, resource_id, label, parent in resources:
                    perms = user_permissions.get(resource_id, (False, False, False, False))
                    cur.execute('''
                        INSERT INTO role_permissions 
                        (role_name, resource_type, resource_id, resource_label, parent_resource_id, 
                         can_view, can_create, can_update, can_delete)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (role_name, resource_type, resource_id) 
                        DO UPDATE SET 
                            resource_label = EXCLUDED.resource_label,
                            parent_resource_id = EXCLUDED.parent_resource_id,
                            can_view = EXCLUDED.can_view,
                            can_create = EXCLUDED.can_create,
                            can_update = EXCLUDED.can_update,
                            can_delete = EXCLUDED.can_delete,
                            updated_at = NOW()
                    ''', ('user', resource_type, resource_id, label, parent, *perms))
                
                conn.commit()
                print("✅ Admin ve User için varsayılan yetkiler eklendi!")
                return True
    except Exception as e:
        print(f"❌ Seed hatası: {e}")
        return False

if __name__ == '__main__':
    print("=" * 50)
    print("Role Permissions Tablosu Oluşturuluyor...")
    print("=" * 50)
    
    if create_permissions_table():
        seed_admin_permissions()
    
    print("=" * 50)
    print("İşlem tamamlandı.")
