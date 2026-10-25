from analysis_pkg import get_batch_model_stats, get_batch_postgres_data, get_postgres_data

# 1. Pull model statistics (loss, accuracy, etc.) for a list of people
people = ["stuffyness", "kovinar", "rguruna", "ch_uz", "aemara84"]
stats_list = get_batch_model_stats(people)

for item in stats_list:
    print(f"Player: {item['person']} | Loss: {item['loss']} | Accuracy: {item['accuracy']}")

# 2. Pull PostgreSQL data for all of those people in unified queries
people_db_data = get_batch_postgres_data(people)
for person, data in people_db_data.items():
    print(person, "Total Games in DB:", data["total_games"], "Model DB Record:", data["model"])

# 3. Run any custom query against PostgreSQL
all_trained_models = get_postgres_data("SELECT player_id, val_loss, val_accuracy FROM models")