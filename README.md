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

### プロジェクトコピー
 python JamaCopyProjects.py

### ログファイル
処理結果は以下に保存されます：
```
output/
├── copy_result_[SOURCE]_to_[TARGET]_[TIMESTAMP].json
├── relationship_mapping_[TIMESTAMP].json
└── dest_relationshiptypes.json
```

### 技術仕様
- **Python**: 3.12以上
- **Jama Connect**: 8.25以上推奨

---

## 更新履歴

- **v1.3**: テストプラン・サイクル完全対応
- **v1.2**: 画像埋め込み・添付ファイル処理追加  
- **v1.1**: フィールド同期・ピックリストマッピング改善
- **v1.0**: 基本的なプロジェクトコピー機能
