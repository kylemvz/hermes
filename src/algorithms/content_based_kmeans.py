import numpy as np
from pyspark.mllib.clustering import KMeans
from . import recommender_helpers as rechelp
from numpy.linalg import norm


def predict(user_info, content_array, num_predictions, k=10, num_partitions=20):
    """Predict ratings for items using a k-means clustering content based
    algorithm designed to increase the diversity of recommended items.

    User profiles are generated by weighting the item vectors by the user's
    rating of the item and summing them.

    The clustering is performed on the item vectors. Items are then drawn from
    these clusters in proportion to the clusters prevalence in the dataset.

    Args:
        user_info (rdd): in the format of (user, item, rating)
        content_array (rdd): content feature array of the items which should be in
            the format of (item, [content_feature vector])
        num_predictions (int): Number of predictions to return

    Returns:
        rdd: in the format of (user, item, predicted_rating)
    """
    # Extract the vectors from the content array
    vectors = content_array.values()
    cluster_model = KMeans.train(vectors, k)
    clustered_content = content_array\
        .map(lambda item_vector1: (cluster_model.predict(item_vector1[1]), (item_vector1[0], item_vector1[1])))

    cluster_centers = cluster_model.centers

    # Calculate the percent of recommendations to make from each cluster
    counts = clustered_content.countByKey()
    fractions = {}
    total = sum([v for k,v in counts.items()])
    for k, v in counts.items():
        fractions[k] = round(float(v) / total, 2)

    # Make the user profiles
    user_keys = user_info.map(lambda user_item_rating: (user_item_rating[1], (user_item_rating[0], user_item_rating[2])))
    user_prefs = content_array\
        .join(user_keys).\
        groupBy(lambda item_item_vector_user_rating: item_item_vector_user_rating[1][1][0])\
        .map(lambda user_array: (user_array[0], rechelp.sum_components(user_array[1])))

    #ensure that there are no user_preference vectors or content vectors with a zero array - this causes the predictions to be nan
    user_prefs = user_prefs.filter(lambda u_id_user_vect: all(v == 0 for v in list(u_id_user_vect[1]))==False)
    clustered_content = clustered_content.filter(lambda cluster_item_item_vector: all(v == 0 for v in list(cluster_item_item_vector[1][1]))==False)

    # Make predictions
    max_rating = user_info.map(lambda user_item_rating2: user_item_rating2[2]).max()
    min_rating = user_info.map(lambda user_item_rating3: user_item_rating3[2]).min()
    diff_ratings = max_rating - min_rating
    content_and_profiles = clustered_content.cartesian(user_prefs).coalesce(num_partitions)
    predictions_with_clusters = content_and_profiles\
        .map(lambda c: (
                c[1][0],
                c[0][0],
                c[0][1][0],
                round(np.dot(c[1][1], c[0][1][1])/(norm(c[0][1][1])*norm(c[1][1])), 3)) )

    clustered_predictions = predictions_with_clusters\
        .groupBy(lambda user_cluster_item_rating: (user_cluster_item_rating[0], user_cluster_item_rating[1]))\
        .flatMap(lambda row: rechelp.sort_and_cut_by_cluster(row, num_predictions, fractions))\
        .map(lambda user_rating_item: (user_rating_item[0], user_rating_item[2], user_rating_item[1]))

    max_pred = clustered_predictions.map(lambda user_item_pred:user_item_pred[2]).max()
    min_pred = clustered_predictions.map(lambda user_item_pred4:user_item_pred4[2]).min()

    diff_pred = float(max_pred - min_pred)

    norm_predictions = clustered_predictions.map(lambda user_item_pred5:(user_item_pred5[0], user_item_pred5[1], \
                    (user_item_pred5[2]-min_pred)*float(diff_ratings/diff_pred)+min_rating))

    return norm_predictions
