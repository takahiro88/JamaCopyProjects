# Jama Project Copier

Jama Project Copierは、Jama Connect インスタンス間でプロジェクトを包括的にコピーするPythonツールです。プロジェクト構造、アイテム、リレーションシップ、テストプラン、テストサイクル、添付ファイルなどを含めた完全なプロジェクト移行を支援します。

## 主要機能

### 🏗️ プロジェクト構造の複製
- **プロジェクトフォルダ対応**: 階層構造を持つプロジェクトフォルダの完全複製
- **アイテムタイプ管理**: 自動的な不足アイテムタイプの作成とフィールド同期
- **ピックリスト同期**: ピックリストとオプションの名前ベースマッピング

### 📋 アイテム・リレーション管理
- **階層構造保持**: 親子関係を維持したアイテムのコピー
- **フィールドマッピング**: `${itemTypeID}`形式のフィールド名自動変換
- **リレーションシップ**: アイテム間の関連性完全保持

### 🧪 テスト機能の完全移行
- **テストプラン**: `post_testplan()`での正確な作成
- **テストグループ**: デフォルトグループ除外での適切な構造複製
- **テストケース**: グループ所属関係の完全移行
- **テストサイクル**: 開始・終了日付でのサイクル管理

### 📎 添付ファイル処理
- **画像埋め込み**: HTML記述内の`<img>`タグ自動処理
- **ファイルアップロード**: 添付ファイルの自動アップロード・URL置換
- **認証対応**: Basic/OAuth認証でのファイルダウンロード

## 環境設定

### 必要パッケージ
```bash
pip install py-jama-rest-client
pip install requests
```

### 環境変数設定

#### Basic認証の場合
```bash
set AUTH_TYPE=BASIC
set JAMA_URL=https://your-target-jama-instance.com
set JAMA_USERNAME=your_username
set JAMA_PASSWORD=your_password
```

#### OAuth認証の場合
```bash
set AUTH_TYPE=OAUTH
set JAMA_URL=https://your-target-jama-instance.com
set JAMA_CLIENT_ID=your_client_id
set JAMA_CLIENT_SECRET=your_client_secret
```

## ファイル構造

### 必要なソースファイル (`copy_from/` フォルダ)
```
copy_from/
├── pick_lists.json                           # ピックリスト定義
├── pick_list_[ID]_options.json              # ピックリストオプション
├── project_itemtypes.json                   # アイテムタイプ定義
├── relationshiptypes.json                   # リレーションシップタイプ
└── project_setting/
    ├── project_[ID].json                     # プロジェクト基本情報
    ├── project_[ID]_items.json               # アイテム一覧
    ├── project_[ID]_relations.json           # リレーション一覧
    ├── project_[ID]_testGroups.json          # テストグループ
    ├── project_[ID]_testGroup_[GID]_testcases.json  # テストケース
    └── attachment_[PID]_[AID]_[filename]     # 添付ファイル
```

### 保存されるデータ
- **プロジェクト階層**: フォルダ構造とプロジェクト関係
- **アイテム**: 全フィールド値とメタデータ
- **リレーション**: アイテム間の関連性
- **テスト構造**: テストプラン、グループ、ケース、サイクル
- **添付ファイル**: 画像・ドキュメント類

## 使用方法

### 1. 基本的なプロジェクトコピー

```python
from JamaCopyProjects import JamaProjectCopier

# インスタンス作成
copier = JamaProjectCopier()

# 利用可能プロジェクト一覧
available_projects = copier.scan_copy_from_projects()
print(f"Available projects: {available_projects}")

# タイプマッピング作成
project_infos = {204: {'name': 'Source Project'}}
used_item_types, used_relationship_types = copier.collect_used_types_from_projects(project_infos)
mappings = copier.create_filtered_type_mappings(used_item_types, used_relationship_types)

# プロジェクトコピー実行
copier.copy_project(
    source_project_id=204,
    new_project_name="Copied Project",
    project_key="COPY001",
    type_id_mapping=mappings[0],
    relationship_type_mapping=mappings[3],
    picklist_option_mapping=mappings[5]
)
```

### 2. 複数プロジェクト一括処理

```python
# 複数プロジェクトの一括処理
for project_id in available_projects:
    project_name, project_key, is_folder, parent_id = copier.load_project_info(project_id)
    
    if not is_folder:  # 通常プロジェクトのみ
        copier.copy_project(
            source_project_id=project_id,
            new_project_name=f"Copy_{project_name}",
            project_key=f"CPY{project_id}",
            type_id_mapping=mappings[0],
            relationship_type_mapping=mappings[3],
            picklist_option_mapping=mappings[5]
        )
```

## 詳細機能

### アイテムタイプ同期
- **自動作成**: 不足するアイテムタイプの自動生成
- **フィールド追加**: 新規フィールドの適切な設定
- **画像処理**: アイテムタイプアイコンの自動変換

### ピックリスト管理
- **名前マッピング**: 同名ピックリストの自動関連付け
- **オプション作成**: 不足オプションの自動生成
- **値変換**: フィールド値の適切なマッピング

### テスト機能詳細

#### テストプラン処理
```python
# itemType 35 (TESTPLAN) の処理
post_testplan(project_id, name, description)
```

#### テストグループ構造
```python
# Default Test Group を除外した処理
for testgroup in testgroups:
    if testgroup['name'] != "Default Test Group":
        post_testgroup(testplan_id, name)
```

#### テストサイクル作成
```python
# 開始・終了日付必須
post_testplans_testcycles(
    testplan_id, 
    testcycle_name, 
    start_date, 
    end_date, 
    testgroups_to_include=group_ids,
    testrun_status_to_include=statuses
)
```

## エラーハンドリング

### 一般的な問題と対処法

#### 1. 認証エラー
```
Error: Authorization failed
```
- 環境変数の設定確認
- 認証情報の有効性検証
- Jama URLの末尾スラッシュ除去

#### 2. ファイル不足エラー
```
Error: project_204_items.json does not exist
```
- `SaveJamaItems.py`での事前データ取得実行
- ファイルパスとプロジェクトID確認

#### 3. API制限エラー
```
Error: Rate limit exceeded
```
- 処理間隔の調整
- `allowed_results_per_page`設定の最適化

### ログメッセージ解説

| レベル | 表示 | 意味 |
|--------|------|------|
| 📋 | Including type | アイテムタイプがマッピング対象に含まれた |
| 🔄 | Mapped | 値やIDが正常にマッピングされた |
| ✅ | Successfully | 処理が正常に完了した |
| ⚠️ | Warning | 警告（処理は継続） |
| ❌ | Error | エラー（当該項目はスキップ） |
| 🚨 | Critical Error | 致命的エラー（処理中断） |

## パフォーマンス最適化

### 推奨設定
```python
# 大量データ処理用設定
super().__init__(
    JAMA_URL, 
    credentials=CREDENTIALS, 
    verify=False, 
    allowed_results_per_page=50  # API制限に応じて調整
)
```

### 処理時間目安
- 小規模プロジェクト（〜100アイテム）: 5-10分
- 中規模プロジェクト（〜1000アイテム）: 30-60分  
- 大規模プロジェクト（1000+アイテム）: 1-3時間

## 制限事項

### 対応外機能
- **ATTACHMENT アイテム**: 別APIでの処理が必要
- **ユーザー・グループ**: ユーザー管理関連は対象外
- **カスタムワークフロー**: 標準フィールドのみ対応

### API制限
- Jama Connect APIの呼び出し制限に従う
- 同時接続数の制限
- データサイズ制限（大容量ファイル非対応）

### 注意事項
- **プロジェクトキー重複**: 既存キーとの衝突回避必要
- **権限要件**: 管理者権限推奨
- **データ整合性**: コピー前後の検証推奨

## トラブルシューティング

### デバッグモード有効化
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### よくある問題

#### プロジェクト作成失敗
```python
# キー重複の確認
existing_projects = list(copier.get_projects())
for project in existing_projects:
    if project.get('fields', {}).get('projectKey') == 'YOUR_KEY':
        print("Key already exists!")
```

#### フィールドマッピング失敗
```python
# フィールド名の確認
for field in source_fields:
    print(f"Field: {field.get('name')} (Type: {field.get('fieldType')})")
```

## サポート・問い合わせ

### ログファイル
処理結果は以下に保存されます：
```
output/
├── copy_result_[SOURCE]_to_[TARGET]_[TIMESTAMP].json
├── relationship_mapping_[TIMESTAMP].json
└── dest_relationshiptypes.json
```

### 技術仕様
- **Python**: 3.7以上
- **Jama Connect**: 8.25以上推奨
- **py-jama-rest-client**: 1.13以上

---

## 更新履歴

- **v1.3**: テストプラン・サイクル完全対応
- **v1.2**: 画像埋め込み・添付ファイル処理追加  
- **v1.1**: フィールド同期・ピックリストマッピング改善
- **v1.0**: 基本的なプロジェクトコピー機能